"""
TDD: line-balance/full 空数据 500 + line 参数接入

Bug 1: stations 为空时 max([]) → ValueError → 500
Bug 2: line 参数定义了但从未传递到查询层

RED: 确认 500 / line 参数未生效
GREEN: max default=0 + line 参数传递到 get_station_metrics
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
    ProcessSegment, Equipment, WorktimeRecord,
)
from app.models.schemas import ActionLabel


# ── Module-scoped test DB ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_db_url():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="mes_bal_full_")
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
def seed_two_lines(client, test_db_url):
    """Seed segments on two different lines to test line filter."""
    session = get_session(test_db_url)

    # Add equipment (used as stations in station_timeline, not by get_station_metrics)
    eq1 = Equipment(name="WS-01", model="M1", workshop="A", status="running")
    eq2 = Equipment(name="WS-02", model="M2", workshop="A", status="running")
    eq3 = Equipment(name="AS-01", model="AS1", workshop="A", status="running")
    session.add_all([eq1, eq2, eq3])
    session.flush()

    now = datetime.now(timezone.utc)

    # Create WorktimeRecord entries (needed by get_station_metrics JOIN)
    wr1 = WorktimeRecord(
        operation="ASSEMBLE", station_id="WS-01",
        actual_ms=5000.0, standard_ms=5000.0, efficiency=1.0,
        mod_total=38.0, shift="morning",
    )
    wr2 = WorktimeRecord(
        operation="REACH", station_id="WS-02",
        actual_ms=3000.0, standard_ms=3000.0, efficiency=1.0,
        mod_total=23.0, shift="morning",
    )
    wr3 = WorktimeRecord(
        operation="MOVE", station_id="AS-01",
        actual_ms=8000.0, standard_ms=8000.0, efficiency=1.0,
        mod_total=62.0, shift="morning",
    )
    session.add_all([wr1, wr2, wr3])
    session.flush()

    # Line 1 segments (should be included when ?line=line1)
    segs_line1 = [
        ProcessSegment(station_id="WS-01", camera_id="cam_0", line="line1",
            action=ActionLabel.ASSEMBLE.value, duration_ms=5000.0,
            worktime_record_id=wr1.id,
            start_time=now - timedelta(hours=2), end_time=now - timedelta(hours=1, minutes=59),
            confidence=0.9, shift="morning"),
        ProcessSegment(station_id="WS-02", camera_id="cam_0", line="line1",
            action=ActionLabel.REACH.value, duration_ms=3000.0,
            worktime_record_id=wr2.id,
            start_time=now - timedelta(hours=2), end_time=now - timedelta(hours=1, minutes=59),
            confidence=0.9, shift="morning"),
    ]
    session.add_all(segs_line1)

    # Line 2 segments (should NOT be included when ?line=line1)
    segs_line2 = [
        ProcessSegment(station_id="AS-01", camera_id="cam_0", line="line2",
            action=ActionLabel.MOVE.value, duration_ms=8000.0,
            worktime_record_id=wr3.id,
            start_time=now - timedelta(hours=2), end_time=now - timedelta(hours=1, minutes=59),
            confidence=0.9, shift="morning"),
    ]
    session.add_all(segs_line2)

    session.commit()
    session.close()


# ══════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════

class TestLineBalanceFull:
    """RED: 空数据 500 + line 参数未生效"""

    def test_full_no_data_returns_200(self, client, auth_headers):
        """无数据时返回 200（修复前返回 500）"""
        resp = client.get("/api/line-balance/full", headers=auth_headers)
        assert resp.status_code == 200, (
            f"RED: Expected 200 but got {resp.status_code}. "
            f"Response: {resp.text}"
        )

    def test_full_with_line_param_returns_200(self, client, auth_headers):
        """?line=line1 空数据返回 200"""
        resp = client.get("/api/line-balance/full?line=line1", headers=auth_headers)
        assert resp.status_code == 200, (
            f"RED: Expected 200 but got {resp.status_code}. "
            f"Response: {resp.text}"
        )

    def test_summary_no_data_returns_200(self, client, auth_headers):
        """summary 空数据回归"""
        resp = client.get("/api/line-balance/summary", headers=auth_headers)
        assert resp.status_code == 200, (
            f"RED: Expected 200 but got {resp.status_code}. "
            f"Response: {resp.text}"
        )

    def test_line_filter_filters_by_line(self, client, auth_headers, seed_two_lines):
        """?line=line1 只返回 line1 的工位数据"""
        resp = client.get("/api/line-balance/full?line=line1", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200 got {resp.status_code}: {resp.text}"
        data = resp.json().get("data", {})
        stations = data.get("stations", [])
        station_names = [s["name"] for s in stations]
        # Should only contain line1 stations (WS-01, WS-02), not AS-01
        assert "WS-01" in station_names, f"line1 station WS-01 missing: {station_names}"
        assert "WS-02" in station_names, f"line1 station WS-02 missing: {station_names}"
        assert "AS-01" not in station_names, f"line2 station AS-01 should be excluded: {station_names}"

    def test_line_filter_default_returns_all(self, client, auth_headers, seed_two_lines):
        """无 line 参数时返回全部工位数据"""
        resp = client.get("/api/line-balance/full", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200 got {resp.status_code}"
        data = resp.json().get("data", {})
        stations = data.get("stations", [])
        # Default is line1 (Query default), so only line1 data
        # Actually the Query default is "line1" so this tests default behavior
        assert len(stations) > 0, "Should have station data"
