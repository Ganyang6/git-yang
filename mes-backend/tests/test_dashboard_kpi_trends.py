"""
RED 阶段：Dashboard KPI trends 应为 dict 而非 list

根因：
  dashboard_kpi 返回 "trends": []（空列表），
  但前端 Dashboard.vue 第 532-566 行访问 d.trends.utilization、d.trends.stdtimeAchievement
  等属性，期望 dict 结构。

RED: 测试预期失败 — trends 是 list, 无法通过 .utilization 访问
GREEN: 将 trends 改为 dict {utilization, stdtimeAchievement, balanceRate, waitLossMinutes} 后通过
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
    ProcessSegment, Equipment,
)
from app.models.schemas import ActionLabel


# -- Module-scoped test DB ----------------------------------------------------

@pytest.fixture(scope="module")
def test_db_url():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="mes_dash_trends_")
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


# ------ Tests ----------------------------------------------------------------

class TestDashboardKpiTrends:
    """trends 字段必须是 dict 且包含所有必要键。"""

    REQUIRED_TREND_KEYS = {"utilization", "stdtimeAchievement", "balanceRate", "waitLossMinutes"}

    def test_trends_is_dict_when_no_data(self, client, auth_headers):
        """无数据时 (today) trends 应为 dict 而非 list。"""
        resp = client.get("/api/dashboard/kpi", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200 got {resp.status_code}: {resp.text}"
        data = resp.json()["data"]
        trends = data.get("trends")
        assert isinstance(trends, dict), (
            f"trends should be a dict but got {type(trends).__name__}: {trends}"
        )

    def test_trends_has_required_keys(self, client, auth_headers):
        """trends 必须包含 utilization/stdtimeAchievement/balanceRate/waitLossMinutes。"""
        resp = client.get("/api/dashboard/kpi", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        trends = data.get("trends")
        assert isinstance(trends, dict), f"trends should be dict, got {type(trends)}"
        missing = self.REQUIRED_TREND_KEYS - set(trends.keys())
        assert not missing, f"trends missing required keys: {missing}"

    def test_trends_values_are_int(self, client, auth_headers):
        """每个趋势值为 int ( -1 / 0 / 1 )。"""
        resp = client.get("/api/dashboard/kpi", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        trends = data.get("trends")
        assert isinstance(trends, dict)
        for key in self.REQUIRED_TREND_KEYS:
            val = trends[key]
            assert isinstance(val, int), (
                f"trends.{key} should be int but got {type(val).__name__}: {val}"
            )
            assert val in (-1, 0, 1), (
                f"trends.{key} should be -1, 0, or 1 but got {val}"
            )

    def test_trends_is_dict_when_has_data(self, client, auth_headers):
        """有数据时 trends 也应为 dict。"""
        # Seed data within today's range
        from app.models.database import get_session
        session = get_session()
        eq = Equipment(name="TREND-TEST", model="M1", workshop="A", status="running")
        session.add(eq)
        session.flush()

        now = datetime.now(timezone.utc)
        seg = ProcessSegment(
            station_id="TREND-TEST", camera_id="cam_0",
            action=ActionLabel.ASSEMBLE.value,
            duration_ms=5000.0, start_time=now - timedelta(hours=1),
            end_time=now - timedelta(hours=1) + timedelta(seconds=5),
            confidence=0.9, shift="morning",
        )
        session.add(seg)
        session.commit()
        session.close()

        # Clear cache so new data is picked up
        from app.api.v1.dashboard import _clear_cache
        _clear_cache()

        resp = client.get("/api/dashboard/kpi", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200 got {resp.status_code}: {resp.text}"
        data = resp.json()["data"]
        trends = data.get("trends")
        assert isinstance(trends, dict), (
            f"trends should be dict even with data, got {type(trends).__name__}: {trends}"
        )
        missing = self.REQUIRED_TREND_KEYS - set(trends.keys())
        assert not missing, f"trends even with data missing keys: {missing}"
