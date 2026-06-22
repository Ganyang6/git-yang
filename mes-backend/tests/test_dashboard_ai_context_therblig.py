"""
RED 阶段: AI context 缺少 Therblig 动素数据

根因:
  GET /api/dashboard/ai-context 只返回7个KPI字段，不包含 therbligDistribution
  和 therbligSummary。AI 收到的 prompt 看不到动素分布信息，无法做 waste 分析。

RED: 测试预期失败 — ai_context 不包含 therbligDistribution
GREEN: 修改 AiContext schema 和 ai_context() 后通过
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-at-least-32b!")
os.environ.setdefault("MES_TEST_MODE", "1")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "changeme")

import tempfile

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from app.models.database import (
    get_session, _engine_cache,
    ProcessSegment, WorktimeRecord, TherbligDetail,
)
from app.models.schemas import ActionLabel


# -- Module-scoped test DB ----------------------------------------------------

@pytest.fixture(scope="module")
def test_db_url():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="mes_ai_ctx_therblig_")
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
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "12345678",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def seed_therblig_data(client, test_db_url):
    """Seed WorktimeRecord + TherbligDetail data for ai_context test."""
    from app.api.v1.dashboard import _clear_cache

    session = get_session(test_db_url)

    # Create a worktime record
    record = WorktimeRecord(
        operation="assembly",
        station_id="WS-01",
        actual_ms=10000.0,
        standard_ms=8000.0,
        efficiency=0.8,
        mod_total=62.0,
        shift="morning",
    )
    session.add(record)
    session.flush()

    # Seed ProcessSegment linked to the worktime record
    now = datetime.now(timezone.utc)
    seg = ProcessSegment(
        camera_id="cam_0",
        station_id="WS-01",
        action=ActionLabel.ASSEMBLE.value,
        start_time=now - timedelta(hours=1),
        end_time=now - timedelta(hours=1) + timedelta(seconds=10),
        duration_ms=10000.0,
        confidence=0.9,
        shift="morning",
        worktime_record_id=record.id,
    )
    session.add(seg)

    # Create TherbligDetails
    details = [
        TherbligDetail(
            worktime_record_id=record.id,
            symbol="R", name="伸手", mod=3.0, actual_ms=1500.0, pct=15.0, is_waste=False,
        ),
        TherbligDetail(
            worktime_record_id=record.id,
            symbol="G", name="抓取", mod=1.0, actual_ms=500.0, pct=5.0, is_waste=False,
        ),
        TherbligDetail(
            worktime_record_id=record.id,
            symbol="M", name="移动", mod=4.0, actual_ms=2000.0, pct=20.0, is_waste=False,
        ),
        TherbligDetail(
            worktime_record_id=record.id,
            symbol="A", name="装配", mod=5.0, actual_ms=4000.0, pct=40.0, is_waste=False,
        ),
        TherbligDetail(
            worktime_record_id=record.id,
            symbol="UD", name="非生产性延误", mod=0.0, actual_ms=2000.0, pct=20.0, is_waste=True,
        ),
    ]
    session.add_all(details)
    session.commit()
    session.close()

    _clear_cache()


class TestAiContextTherblig:
    """ai_context 必须包含 therbligDistribution 和 therbligSummary 字段。"""

    def test_ai_context_has_therblig_fields(self, client, auth_headers, seed_therblig_data):
        """RED: ai_context 缺少 therbligDistribution 和 therbligSummary。"""
        resp = client.get("/api/dashboard/ai-context", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200 got {resp.status_code}: {resp.text}"
        data = resp.json()["data"]

        assert "therbligDistribution" in data, (
            "RED: ai_context missing therbligDistribution field"
        )
        assert "therbligSummary" in data, (
            "RED: ai_context missing therbligSummary field"
        )

    def test_therblig_distribution_is_list(self, client, auth_headers, seed_therblig_data):
        """RED: therbligDistribution 不是 list。"""
        resp = client.get("/api/dashboard/ai-context", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        dist = data.get("therbligDistribution", [])
        assert isinstance(dist, list), (
            f"RED: therbligDistribution should be list, got {type(dist).__name__}"
        )

    def test_therblig_summary_has_required_keys(self, client, auth_headers, seed_therblig_data):
        """RED: therbligSummary 缺少 required keys。"""
        resp = client.get("/api/dashboard/ai-context", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        summary = data.get("therbligSummary", {})
        required_keys = {"totalSymbols", "wasteCount", "wasteRatio"}
        missing = required_keys - set(summary.keys())
        assert not missing, (
            f"RED: therbligSummary missing required keys: {missing}"
        )

    def test_distribution_items_have_expected_structure(self, client, auth_headers, seed_therblig_data):
        """RED: distribution 内每个元素缺少必要字段。"""
        resp = client.get("/api/dashboard/ai-context", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        dist = data.get("therbligDistribution", [])
        if dist:
            item = dist[0]
            for key in ("symbol", "name", "pct", "isWaste"):
                assert key in item, (
                    f"RED: therbligDistribution item missing '{key}'"
                )
