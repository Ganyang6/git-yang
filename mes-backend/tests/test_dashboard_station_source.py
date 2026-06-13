"""
TDD Step 5 — Dashboard station_timeline 从 Station 表读数据

目标:
  station_timeline() 目前查 Equipment 表，改为查 Station 表。

🔴 RED: 此测试在修改前失败（因 Station 表未 seed / Equipment 表被查询）
🟩 GREEN: 修改 production code 后测试通过
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
    ProcessSegment, Equipment, Station,
)
from app.models.schemas import ActionLabel


# -- Module-scoped test DB ----------------------------------------------------

@pytest.fixture(scope="module")
def test_db_url():
    """Create a dedicated temp DB for these tests."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="mes_dash_station_")
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
    """FastAPI test client backed by the dedicated module DB."""
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    """Login as admin and return auth headers."""
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "12345678",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def seed_station_and_segments(client, test_db_url):
    """Seed Station rows + ProcessSegment data.

    Equipment 表故意保持为空，以验证不依赖 Equipment 表。
    """
    session = get_session(test_db_url)

    # Seed Station data (no Equipment rows at all)
    st1 = Station(name="WS-A1", worker="小李", line="组装产线", shift="早班")
    st2 = Station(name="WS-A2", worker="小王", line="组装产线", shift="早班")
    st3 = Station(name="WS-B1", worker="小张", line="测试产线", shift="中班")
    session.add_all([st1, st2, st3])
    session.flush()

    now = datetime.now(timezone.utc)
    base_time = now - timedelta(minutes=30)

    segs = [
        # WS-A1 segments
        ProcessSegment(
            station_id="WS-A1", camera_id="cam_0",
            action=ActionLabel.ASSEMBLE.value,
            duration_ms=5000.0, start_time=base_time,
            end_time=base_time + timedelta(seconds=5),
            confidence=0.9, shift="morning",
        ),
        ProcessSegment(
            station_id="WS-A1", camera_id="cam_0",
            action=ActionLabel.WAIT.value,
            duration_ms=2000.0, start_time=base_time + timedelta(seconds=10),
            end_time=base_time + timedelta(seconds=12),
            confidence=0.9, shift="morning",
        ),
        # WS-A2 segments
        ProcessSegment(
            station_id="WS-A2", camera_id="cam_0",
            action=ActionLabel.REACH.value,
            duration_ms=3000.0, start_time=base_time,
            end_time=base_time + timedelta(seconds=3),
            confidence=0.9, shift="morning",
        ),
        # WS-B1 segments
        ProcessSegment(
            station_id="WS-B1", camera_id="cam_1",
            action=ActionLabel.INSPECT.value,
            duration_ms=4000.0, start_time=base_time,
            end_time=base_time + timedelta(seconds=4),
            confidence=0.9, shift="afternoon",
        ),
    ]
    session.add_all(segs)
    session.commit()
    session.close()


# ------ Tests ----------------------------------------------------------------

class TestDashboardStationSource:
    """station_timeline 的数据源应从 Equipment 改为 Station 表。"""

    def test_station_timeline_uses_station_table(
        self, client, auth_headers, seed_station_and_segments
    ):
        """Station 表有数据时，返回数据应包含 Station 的 name/worker/line/shift 信息。"""
        resp = client.get("/api/stations/timeline", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"

        data = resp.json()
        assert "data" in data, f"Response missing 'data' key: {data}"
        timeline = data["data"]

        # Should return all 3 seeded stations
        assert len(timeline) == 3, f"Expected 3 stations, got {len(timeline)}: {timeline}"

        # Collect names for easy assertion
        names = [item["name"] for item in timeline]
        assert "WS-A1" in names, f"Expected WS-A1 in {names}"
        assert "WS-A2" in names, f"Expected WS-A2 in {names}"
        assert "WS-B1" in names, f"Expected WS-B1 in {names}"

        # Each entry should have the expected shape
        for item in timeline:
            assert "id" in item, f"Item missing 'id': {item}"
            assert "name" in item, f"Item missing 'name': {item}"
            assert "oee" in item, f"Item missing 'oee': {item}"
            assert "segments" in item, f"Item missing 'segments': {item}"

        # Verify WS-A1 has segments (ASSEMBLE + WAIT)
        ws_a1 = next(item for item in timeline if item["name"] == "WS-A1")
        assert len(ws_a1["segments"]) > 0, f"WS-A1 should have segments: {ws_a1}"

    def test_equipment_table_not_queried(
        self, client, auth_headers, seed_station_and_segments
    ):
        """Equipment 表有数据时，timeline 应返回 Station 表数据而非 Equipment 表数据。

        证明 station_timeline 不再依赖 Equipment 表。
        Equipment 的 auto-seed 数据（WS-01…WS-05）不应出现在响应中。
        """
        resp = client.get("/api/stations/timeline", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"

        data = resp.json()
        assert "data" in data
        timeline = data["data"]

        # Should return Station table data, not Equipment auto-seed data
        assert len(timeline) > 0, "Expected non-empty timeline"

        names = [item["name"] for item in timeline]

        # Station names should be present
        assert "WS-A1" in names, f"Expected Station name in response, got: {names}"
        assert "WS-A2" in names, f"Expected Station name in response, got: {names}"
        assert "WS-B1" in names, f"Expected Station name in response, got: {names}"

        # Equipment auto-seed names should NOT be present
        # (Equipment table has WS-01…WS-05 from init_db seeding)
        equipment_defaults = ["WS-01", "WS-02", "WS-03", "WS-04", "WS-05"]
        for eq_name in equipment_defaults:
            assert eq_name not in names, (
                f"Equipment default '{eq_name}' should NOT appear in timeline. "
                f"Timeline returns Station data, not Equipment data. Names: {names}"
            )
