"""
全量审计：方案A（元数据API）+ 方案B（计算下沉 + 状态协议）

RED 阶段：编写失败测试 → 验证 → GREEN 阶段修复

审计清单：
  A1. /api/meta 端点完整字段
  A2. 前端 meta 替换硬编码（LineBalance, WorktimeAnalysis, Dashboard）
  B1. LineBalance 计算下沉
  B2. Worktime standardTime/efficiency 从 API 取
  B3. 状态协议 hasData
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-at-least-32b!")
os.environ.setdefault("MES_TEST_MODE", "1")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "changeme")

import tempfile

import pytest
from fastapi.testclient import TestClient

from app.models.database import (
    get_session, init_db, _engine_cache,
    ProcessSegment, TherbligDetail, WorktimeRecord,
    Equipment,
)
from app.models.schemas import ActionLabel


# ── Session-scoped test DB ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_db_url():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="mes_audit_")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    os.environ["MES_DB_URL"] = db_url
    _engine_cache.clear()
    yield db_url
    os.environ.pop("MES_DB_URL", None)
    _engine_cache.clear()
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture(scope="module")
def client(test_db_url):
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    # The config.yaml password hash is for password "12345678"
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "12345678",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def seed_data(client, test_db_url):
    """Seed minimal test data for KPIs and worktime."""
    session = get_session(test_db_url)

    # Add some equipment
    eq1 = Equipment(name="WS-01", model="M1", workshop="A", status="running")
    eq2 = Equipment(name="WS-02", model="M2", workshop="A", status="running")
    session.add_all([eq1, eq2])
    session.flush()

    # Add process segments for KPI computation
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    from datetime import timedelta
    segs = [
        ProcessSegment(station_id="WS-01", camera_id="cam_0",
                       action=ActionLabel.ASSEMBLE.value,
                       duration_ms=5000.0, start_time=now - timedelta(hours=1),
                       end_time=now, confidence=0.9, shift="morning"),
        ProcessSegment(station_id="WS-02", camera_id="cam_0",
                       action=ActionLabel.REACH.value,
                       duration_ms=3000.0, start_time=now - timedelta(hours=1),
                       end_time=now, confidence=0.9, shift="morning"),
        ProcessSegment(station_id="WS-01", camera_id="cam_0",
                       action=ActionLabel.WAIT.value,
                       duration_ms=1000.0, start_time=now - timedelta(hours=1),
                       end_time=now, confidence=0.9, shift="morning"),
    ]
    session.add_all(segs)
    session.flush()

    # Add a worktime record + therblig detail for therblig detail endpoint
    record = WorktimeRecord(
        operation="TestOp",
        station_id="WS-01",
        actual_ms=15000.0,
        standard_ms=12000.0,
        efficiency=0.80,
        mod_total=93.0,
    )
    session.add(record)
    session.flush()

    detail = TherbligDetail(
        worktime_record_id=record.id,
        symbol="RE",
        name="Reach",
        mod=6.0,
        actual_ms=2000.0,
        pct=25.0,
        is_waste=False,
    )
    session.add(detail)
    session.commit()
    session.close()

    return {"record_id": record.id}


# ══════════════════════════════════════════════════════════════════════════
# A1. /api/meta 端点 — 字段完整性
# ══════════════════════════════════════════════════════════════════════════


class TestA1_MetaCompleteness:
    """RED: /api/meta 必须返回全部必要字段。"""

    def test_meta_stations_field(self, client, auth_headers):
        """stations 字段必须存在且为 list"""
        resp = client.get("/api/meta", headers=auth_headers)
        data = resp.json().get("data", {})
        assert "stations" in data, "A1: 缺少 stations"
        assert isinstance(data["stations"], list), "A1: stations 应为 list"

    def test_meta_shifts_field(self, client, auth_headers):
        """shifts 字段必须存在且为 list"""
        resp = client.get("/api/meta", headers=auth_headers)
        data = resp.json().get("data", {})
        assert "shifts" in data, "A1: 缺少 shifts"
        assert isinstance(data["shifts"], list), "A1: shifts 应为 list"
        assert len(data["shifts"]) > 0, "A1: shifts 不应为空"

    def test_meta_lines_field(self, client, auth_headers):
        """lines 字段必须存在且为 list"""
        resp = client.get("/api/meta", headers=auth_headers)
        data = resp.json().get("data", {})
        assert "lines" in data, "A1: 缺少 lines"
        assert isinstance(data["lines"], list), "A1: lines 应为 list"

    def test_meta_mod_unit_positive(self, client, auth_headers):
        """mod_unit 必须存在且为正值（<1 秒）"""
        resp = client.get("/api/meta", headers=auth_headers)
        data = resp.json().get("data", {})
        assert "mod_unit" in data, "A1: 缺少 mod_unit"
        assert 0 < data["mod_unit"] < 1, "A1: mod_unit 应在 (0,1) 范围内"

    def test_meta_thresholds_field(self, client, auth_headers):
        """thresholds 必须存在且包含 balance_rate"""
        resp = client.get("/api/meta", headers=auth_headers)
        data = resp.json().get("data", {})
        assert "thresholds" in data, "A1: 缺少 thresholds"
        th = data["thresholds"]
        assert isinstance(th, dict), "A1: thresholds 应为 dict"
        assert "balance_rate" in th, "A1: thresholds 缺少 balance_rate"
        assert "efficiency" in th, "A1: thresholds 缺少 efficiency"
        assert "waste_ratio" in th, "A1: thresholds 缺少 waste_ratio"

    def test_meta_thresholds_balance_rate_structure(self, client, auth_headers):
        """balance_rate 阈值必须有 excellent_min 和 fair_min"""
        resp = client.get("/api/meta", headers=auth_headers)
        th = resp.json().get("data", {}).get("thresholds", {})
        br = th.get("balance_rate", {})
        assert "excellent_min" in br, "A1: balance_rate 缺少 excellent_min"
        assert "fair_min" in br, "A1: balance_rate 缺少 fair_min"
        assert br["excellent_min"] > br["fair_min"], \
            "A1: excellent_min 应大于 fair_min"

    def test_meta_thresholds_efficiency_structure(self, client, auth_headers):
        """efficiency 阈值必须有 normal_min 和 fast_min"""
        resp = client.get("/api/meta", headers=auth_headers)
        th = resp.json().get("data", {}).get("thresholds", {})
        eff = th.get("efficiency", {})
        assert "normal_min" in eff, "A1: efficiency 缺少 normal_min"
        assert "fast_min" in eff, "A1: efficiency 缺少 fast_min"
        assert eff["fast_min"] > eff["normal_min"], \
            "A1: fast_min 应大于 normal_min"

    def test_meta_thresholds_waste_ratio_structure(self, client, auth_headers):
        """waste_ratio 阈值必须有 warning_min 和 danger_min"""
        resp = client.get("/api/meta", headers=auth_headers)
        th = resp.json().get("data", {}).get("thresholds", {})
        wr = th.get("waste_ratio", {})
        assert "warning_min" in wr, "A1: waste_ratio 缺少 warning_min"
        assert "danger_min" in wr, "A1: waste_ratio 缺少 danger_min"
        assert wr["danger_min"] > wr["warning_min"], \
            "A1: danger_min 应大于 warning_min"

    def test_meta_requires_auth(self, client):
        """未登录请求应返回 401。在 MES_TEST_MODE 下 auth 被跳过，
        此测试仅在非测试模式时验证。"""
        import os
        if os.environ.get("MES_TEST_MODE", "").lower() in ("1", "true", "yes"):
            pytest.skip("MES_TEST_MODE 启用时 auth 被绕过")
        resp = client.get("/api/meta")
        assert resp.status_code == 401, "A1: 未认证应返回 401"


# ══════════════════════════════════════════════════════════════════════════
# B1. LineBalance 计算下沉 — 后端返回 balanceRate/smoothIndex
# ══════════════════════════════════════════════════════════════════════════


class TestB1_LineBalanceCalcSinking:
    """RED: LineBalance API 必须返回 balanceRate 和 smoothIndex，
    前端不复算。"""

    def test_line_balance_full_returns_balance_rate(self, client, auth_headers):
        """line-balance/full 响应必须包含 balanceRate"""
        resp = client.get("/api/line-balance/full?line=line1", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "balanceRate" in data, "B1: 缺少 balanceRate"
        br = data["balanceRate"]
        assert br is None or isinstance(br, (int, float)), f"B1: balanceRate 应为数字/None, got {type(br)}"
        if br is not None:
            assert 0 <= br <= 1, f"B1: balanceRate 应在 [0,1] 范围, got {br}"

    def test_line_balance_full_returns_smooth_index(self, client, auth_headers):
        """line-balance/full 响应必须包含 smoothIndex"""
        resp = client.get("/api/line-balance/full?line=line1", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "smoothIndex" in data, "B1: 缺少 smoothIndex"
        si = data["smoothIndex"]
        assert si is None or isinstance(si, (int, float)), f"B1: smoothIndex 应为数字/None, got {type(si)}"

    def test_line_balance_summary_returns_balance_rate(self, client, auth_headers):
        """line-balance/summary 响应必须包含 balanceRate"""
        resp = client.get("/api/line-balance/summary", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "balanceRate" in data, "B1-summary: 缺少 balanceRate"
        assert "smoothIndex" in data, "B1-summary: 缺少 smoothIndex"

    def test_line_balance_full_returns_stations(self, client, auth_headers):
        """line-balance/full 必须返回 stations 数组"""
        resp = client.get("/api/line-balance/full?line=line1", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "stations" in data, "B1: 缺少 stations"
        assert isinstance(data["stations"], list), "B1: stations 应为 list"


# ══════════════════════════════════════════════════════════════════════════
# B2. Worktime standardTime/efficiency 从 API 取
# ══════════════════════════════════════════════════════════════════════════


class TestB2_WorktimeFromApi:
    """RED: Worktime detail API 必须返回 standardTime 和 efficiency，
    前端不复算。"""

    def test_worktime_therblig_detail_returns_standard_time(self, client, auth_headers, seed_data):
        """worktime/therblig/{id} 必须返回 standardTime"""
        op_id = seed_data["record_id"]
        resp = client.get(f"/api/v1/worktime/therblig/{op_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "standardTime" in data, f"B2: 缺少 standardTime, body={resp.text}"
        assert isinstance(data["standardTime"], (int, float)), \
            f"B2: standardTime 应为数字, got {type(data['standardTime'])}"

    def test_worktime_therblig_detail_returns_efficiency(self, client, auth_headers, seed_data):
        """worktime/therblig/{id} 必须返回 efficiency"""
        op_id = seed_data["record_id"]
        resp = client.get(f"/api/v1/worktime/therblig/{op_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "efficiency" in data, f"B2: 缺少 efficiency, body={resp.text}"
        assert isinstance(data["efficiency"], (int, float)), \
            f"B2: efficiency 应为数字, got {type(data['efficiency'])}"

    def test_worktime_therblig_detail_returns_allowance_rate(self, client, auth_headers, seed_data):
        """worktime/therblig/{id} 必须返回 allowanceRate"""
        op_id = seed_data["record_id"]
        resp = client.get(f"/api/v1/worktime/therblig/{op_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "allowanceRate" in data, f"B2: 缺少 allowanceRate"
        assert isinstance(data["allowanceRate"], (int, float)), \
            f"B2: allowanceRate 应为数字"

    def test_worktime_therblig_detail_no_normal_time(self, client, auth_headers, seed_data):
        """worktime/therblig/{id} 不应包含 normalTime"""
        op_id = seed_data["record_id"]
        resp = client.get(f"/api/v1/worktime/therblig/{op_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "normalTime" not in data, "B2: normalTime 应已删除"


# ══════════════════════════════════════════════════════════════════════════
# B3. 状态协议 — hasData 字段
# ══════════════════════════════════════════════════════════════════════════


class TestB3_StatusProtocol:
    """RED: 可空字段必须有 hasData 标志，前端据此区分"有数据但为 0"和"无数据"。

    格式约定：
      对每个可空字段 X，在 API 响应中额外提供 X_hasData (bool)。
      不改变已有字段名（不改已有合约）。
    """

    # ── Dashboard KPI ────────────────────────────────────────────────

    def test_dashboard_kpi_utilization_has_data(self, client, auth_headers, seed_data):
        """dashboard/kpi utilization 必须有 utilization_hasData"""
        resp = client.get("/api/dashboard/kpi", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "utilization" in data, "B3: 缺少 utilization"
        assert "utilization_hasData" in data, "B3: 缺少 utilization_hasData"
        assert isinstance(data["utilization_hasData"], bool), \
            "B3: utilization_hasData 须为 bool"

    def test_dashboard_kpi_stdtime_achievement_has_data(self, client, auth_headers, seed_data):
        """dashboard/kpi stdtimeAchievement 必须有 stdtimeAchievement_hasData"""
        resp = client.get("/api/dashboard/kpi", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "stdtimeAchievement_hasData" in data, \
            "B3: 缺少 stdtimeAchievement_hasData"
        assert isinstance(data["stdtimeAchievement_hasData"], bool)

    def test_dashboard_kpi_balance_rate_has_data(self, client, auth_headers, seed_data):
        """dashboard/kpi balanceRate 必须有 balanceRate_hasData"""
        resp = client.get("/api/dashboard/kpi", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "balanceRate_hasData" in data, "B3: 缺少 balanceRate_hasData"
        assert isinstance(data["balanceRate_hasData"], bool)

    def test_dashboard_kpi_wait_loss_minutes_has_data(self, client, auth_headers, seed_data):
        """dashboard/kpi waitLossMinutes 必须有 waitLossMinutes_hasData"""
        resp = client.get("/api/dashboard/kpi", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "waitLossMinutes_hasData" in data, \
            "B3: 缺少 waitLossMinutes_hasData"
        assert isinstance(data["waitLossMinutes_hasData"], bool)

    def test_dashboard_kpi_has_data_true_with_data(self, client, auth_headers, seed_data):
        """有 segment 数据时 hasData 应为 True"""
        resp = client.get("/api/dashboard/kpi", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        # 我们 seed 了 3 个 segment
        assert data["utilization_hasData"] is True, \
            "B3: 有数据时 utilization_hasData 应为 True"
        assert data["stdtimeAchievement_hasData"] is True, \
            "B3: 有数据时 stdtimeAchievement_hasData 应为 True"

    # ── Reports KPI ─────────────────────────────────────────────────

    def test_reports_kpi_yield_rate_has_data(self, client, auth_headers, seed_data):
        """reports/kpi yieldRate 必须有 yieldRate_hasData"""
        resp = client.get("/api/reports/kpi", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "yieldRate" in data, "B3: 缺少 yieldRate"
        assert "yieldRate_hasData" in data, "B3: 缺少 yieldRate_hasData"
        assert isinstance(data["yieldRate_hasData"] if "yieldRate_hasData" in data else None, bool), \
            "B3: yieldRate_hasData 须为 bool"

    def test_reports_kpi_oee_has_data(self, client, auth_headers, seed_data):
        """reports/kpi oee 必须有 oee_hasData"""
        resp = client.get("/api/reports/kpi", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "oee" in data, "B3: 缺少 oee"
        assert "oee_hasData" in data, "B3: 缺少 oee_hasData"
        assert isinstance(data["oee_hasData"] if "oee_hasData" in data else None, bool), \
            "B3: oee_hasData 须为 bool"

    def test_reports_kpi_completion_rate_has_data(self, client, auth_headers, seed_data):
        """reports/kpi completionRate 必须有 completionRate_hasData"""
        resp = client.get("/api/reports/kpi", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "completionRate_hasData" in data, \
            "B3: 缺少 completionRate_hasData"
        assert isinstance(data["completionRate_hasData"] if "completionRate_hasData" in data else None, bool), \
            "B3: completionRate_hasData 须为 bool"

    def test_reports_kpi_on_time_rate_has_data(self, client, auth_headers, seed_data):
        """reports/kpi onTimeRate 必须有 onTimeRate_hasData"""
        resp = client.get("/api/reports/kpi", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "onTimeRate_hasData" in data, "B3: 缺少 onTimeRate_hasData"
        assert isinstance(data["onTimeRate_hasData"] if "onTimeRate_hasData" in data else None, bool), \
            "B3: onTimeRate_hasData 须为 bool"

    def test_reports_kpi_total_output_has_data(self, client, auth_headers, seed_data):
        """reports/kpi totalOutput 必须有 totalOutput_hasData"""
        resp = client.get("/api/reports/kpi", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json().get("data", {})
        assert "totalOutput_hasData" in data, "B3: 缺少 totalOutput_hasData"
        assert isinstance(data["totalOutput_hasData"] if "totalOutput_hasData" in data else None, bool), \
            "B3: totalOutput_hasData 须为 bool"


# ══════════════════════════════════════════════════════════════════════════
# A2. 前端 meta 使用验证
# ══════════════════════════════════════════════════════════════════════════


class TestA2_FrontendMetaUsage:
    """验证 /api/meta 返回的数据能被前端各页面使用"""

    def test_meta_stations_match_equipment(self, client, auth_headers, seed_data):
        """工位列表应与 equipment 表一致"""
        meta = client.get("/api/meta", headers=auth_headers).json()
        eq = client.get("/api/equipment", headers=auth_headers).json()
        meta_stations = {s['id'] for s in meta.get('data', {}).get('stations', [])}
        eq_items = {e['name'] for e in eq.get('data', {}).get('items', [])}
        assert meta_stations == eq_items, 'meta stations 应与 equipment 匹配'

    def test_meta_thresholds_used_by_dashboard(self, client, auth_headers, seed_data):
        """阈值结构应与 Dashboard.vue 消费端一致"""
        meta = client.get("/api/meta", headers=auth_headers).json()
        t = meta.get('data', {}).get('thresholds', {})
        assert 'balance_rate' in t
        assert 'excellent_min' in t['balance_rate']
        assert 'fair_min' in t['balance_rate']
        assert 'efficiency' in t
        assert 'waste_ratio' in t


# ══════════════════════════════════════════════════════════════════════════
# B3b. AI Context — 空数据库 hasData
# ══════════════════════════════════════════════════════════════════════════


class TestB3b_AiContextEmptyDb:
    """RED: ai_context 空数据库时返回 hasData=false，所有指标为 null。"""

    def test_ai_context_empty_db_has_data_false(self, auth_headers):
        """空数据库时 /api/dashboard/ai-context 应返回 hasData=false，不返回误导值。"""
        import os
        import tempfile
        from fastapi.testclient import TestClient
        from app.models.database import get_session, init_db, _engine_cache
        from app.api.v1.dashboard import _clear_cache

        # 创建临时空数据库
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db_url = f"sqlite:///{path}"

        # 切换到空数据库
        old_db_url = os.environ.get("MES_DB_URL", "")
        os.environ["MES_DB_URL"] = db_url
        _engine_cache.clear()
        _clear_cache()
        init_db(db_url=db_url, echo=False)

        from app.main import app
        with TestClient(app) as empty_client:
            # 用 config.yaml 中的密码登录
            login_resp = empty_client.post("/api/auth/login", json={
                "username": "admin",
                "password": "12345678",
            })
            if login_resp.status_code != 200:
                pytest.skip(f"Login failed on empty DB: {login_resp.text}")
            token = login_resp.json()["data"]["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            resp = empty_client.get("/api/dashboard/ai-context", headers=headers)

        # 清理
        os.environ["MES_DB_URL"] = old_db_url
        _engine_cache.clear()

        assert resp.status_code == 200, f"Status: {resp.status_code}, body: {resp.text}"
        data = resp.json()["data"]
        assert data.get("hasData") is False, f"Expected hasData=False, got {data}"

        # 当 hasData=False 时，关键指标应为 None，不是 0 或 100
        for field in ["balanceRate", "taktTime", "lostCapacity", "utilization", "stdtimeAchievement", "wasteRatio"]:
            assert data.get(field) is None, f"Field {field} should be None when hasData=False, got {data.get(field)}"
