"""
RED 阶段：dashboard KPI week 范围 500 回归测试

根因：
  dashboard_kpi 的 range=week/30 跨长时间窗口，但
  compute_line_balance_rate(session) 硬编码 range_hours=8.0，
  导致 7 天内有 segments 但最近 8 小时无数据时：
    total_ms > 0 -> 不返回空数据 -> lbr=None -> round(None,4) TypeError -> 500

RED: 此测试预期失败（500），证明 bug 存在
GREEN: compute_line_balance_rate 传入正确的 range_start 后，测试应通过
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
    fd, path = tempfile.mkstemp(suffix=".db", prefix="mes_dash_week_")
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
def seed_old_data(client, test_db_url):
    """Seed segments that are >8h old but within 7 days."""
    session = get_session(test_db_url)

    eq1 = Equipment(name="WS-01", model="M1", workshop="A", status="running")
    eq2 = Equipment(name="WS-02", model="M2", workshop="A", status="running")
    session.add_all([eq1, eq2])
    session.flush()

    now = datetime.now(timezone.utc)

    old_time = now - timedelta(days=2, hours=0)
    segs = [
        ProcessSegment(
            station_id="WS-01", camera_id="cam_0",
            action=ActionLabel.ASSEMBLE.value,
            duration_ms=5000.0, start_time=old_time,
            end_time=old_time + timedelta(seconds=5),
            confidence=0.9, shift="morning",
        ),
        ProcessSegment(
            station_id="WS-02", camera_id="cam_0",
            action=ActionLabel.REACH.value,
            duration_ms=3000.0, start_time=old_time,
            end_time=old_time + timedelta(seconds=3),
            confidence=0.9, shift="morning",
        ),
        ProcessSegment(
            station_id="WS-01", camera_id="cam_0",
            action=ActionLabel.WAIT.value,
            duration_ms=1000.0, start_time=old_time,
            end_time=old_time + timedelta(seconds=1),
            confidence=0.9, shift="morning",
        ),
    ]
    session.add_all(segs)
    session.commit()
    session.close()


# ------ Tests ----------------------------------------------------------------

class TestDashboardKpiWeekRange:
    """dashboard_kpi?range=week 在不匹配的时间窗口下应返回200而非500。"""

    def test_kpi_week_returns_200(self, client, auth_headers, seed_old_data):
        resp = client.get("/api/dashboard/kpi?range=week", headers=auth_headers)
        assert resp.status_code == 200, (
            f"Expected 200 but got {resp.status_code}. Response: {resp.text}"
        )
        data = resp.json()
        assert "data" in data
        dd = data["data"]
        assert "utilization" in dd
        assert "balanceRate" in dd
        assert "stdtimeAchievement" in dd

    def test_kpi_month_returns_200(self, client, auth_headers, seed_old_data):
        resp = client.get("/api/dashboard/kpi?range=month", headers=auth_headers)
        assert resp.status_code == 200, (
            f"Expected 200 but got {resp.status_code}. Response: {resp.text}"
        )

    def test_kpi_today_no_data_graceful(self, client, auth_headers, seed_old_data):
        resp = client.get("/api/dashboard/kpi?range=today", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200 got {resp.status_code}: {resp.text}"
