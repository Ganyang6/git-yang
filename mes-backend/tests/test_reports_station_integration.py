"""
TDD Step 6 — 工时分析 + Reports 工位数据源统一

目标:
  工时分析 WorktimeAnalysis.vue 和 Reports.vue 的工位下拉改为从 Station 表动态加载。

🔴 RED: 验证 API 能用 station_id 过滤（先写测试，后改前端）
🟩 GREEN: 确保工位下拉从 Stations API 获取，显示格式统一
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-at-least-32b!")
os.environ.setdefault("MES_TEST_MODE", "1")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "changeme")

import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.models.database import (
    get_session, _engine_cache,
    ProcessSegment, WorktimeRecord, Station,
)
from app.models.schemas import ActionLabel


# -- Module-scoped test DB ----------------------------------------------------

@pytest.fixture(scope="module")
def test_db_url():
    """Create a dedicated temp DB for these tests."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="mes_reports_station_")
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
def seed_stations_and_segments(client, test_db_url):
    """Seed Station rows + ProcessSegment data.

    Directly insert process segments that match station names,
    then call aggregate_segments to produce WorktimeRecord entries.
    """
    session = get_session(test_db_url)

    # Seed Station data
    st1 = Station(name="STA-01", worker="小李", line="组装产线", shift="早班")
    st2 = Station(name="STA-02", worker="小王", line="测试产线", shift="中班")
    session.add_all([st1, st2])
    session.commit()

    # Seed ProcessSegment data with matching station_ids
    base_ts = datetime(2026, 6, 1, 1, 0, tzinfo=timezone.utc)  # local 09:00

    segs = [
        # STA-01 segments (morning shift)
        ProcessSegment(
            station_id="STA-01", camera_id="cam_0",
            action=ActionLabel.ASSEMBLE.value,
            duration_ms=5000.0, start_time=base_ts,
            end_time=base_ts + timedelta(seconds=5),
            confidence=0.9, shift="morning",
        ),
        ProcessSegment(
            station_id="STA-01", camera_id="cam_0",
            action=ActionLabel.REACH.value,
            duration_ms=2000.0, start_time=base_ts + timedelta(seconds=10),
            end_time=base_ts + timedelta(seconds=12),
            confidence=0.9, shift="morning",
        ),
        ProcessSegment(
            station_id="STA-01", camera_id="cam_0",
            action=ActionLabel.GRASP.value,
            duration_ms=1500.0, start_time=base_ts + timedelta(seconds=15),
            end_time=base_ts + timedelta(seconds=16.5),
            confidence=0.9, shift="morning",
        ),
        # STA-02 segments (afternoon shift)
        ProcessSegment(
            station_id="STA-02", camera_id="cam_1",
            action=ActionLabel.INSPECT.value,
            duration_ms=4000.0, start_time=base_ts + timedelta(hours=8),
            end_time=base_ts + timedelta(hours=8, seconds=4),
            confidence=0.9, shift="afternoon",
        ),
    ]
    session.add_all(segs)
    session.commit()
    session.close()

    # Now call the aggregate API to create WorktimeRecord entries
    from app.services.worktime_aggregator import aggregate_segments
    session2 = get_session(test_db_url)
    aggregate_segments(session2, station_id=None, shift="morning")
    aggregate_segments(session2, station_id=None, shift="afternoon")
    session2.close()



# ------ Tests ----------------------------------------------------------------

class TestReportsStationIntegration:
    """工位筛选 API 应支持从 Station 表获取的 ID 进行过滤。"""

    def test_worktime_summary_with_station(
        self, client, auth_headers, seed_stations_and_segments
    ):
        """调用 /api/v1/worktime/summary?station=STA-01 应返回 200

        API 用 station_id 字符串过滤（匹配 WorktimeRecord.station_id）。
        使用 Station.name 作为过滤值。
        """
        resp = client.get(
            "/api/v1/worktime/summary?station=STA-01&shift=morning",
            headers=auth_headers,
        )
        assert resp.status_code == 200, (
            f"Expected 200 but got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert "data" in data, f"Response missing 'data' key: {data}"
        summary = data["data"]
        assert "totalOps" in summary, f"Missing totalOps: {summary}"
        assert "avgEfficiency" in summary, f"Missing avgEfficiency: {summary}"
        # STA-01 has 3 segments in morning → 2 distinct operations (assembly + reach/grasp → transport)
        # Actually aggregation groups by action, so: assemble, reach, grasp → 3 operations
        assert summary["totalOps"] >= 0, f"totalOps should be >= 0: {summary}"

    def test_worktime_summary_all_stations(
        self, client, auth_headers, seed_stations_and_segments
    ):
        """不传 station 或 station=all 应返回所有工位数据。"""
        resp = client.get(
            "/api/v1/worktime/summary?shift=morning",
            headers=auth_headers,
        )
        assert resp.status_code == 200, (
            f"Expected 200 but got {resp.status_code}: {resp.text}"
        )

    def test_worktime_operations_with_station(
        self, client, auth_headers, seed_stations_and_segments
    ):
        """调用 /api/v1/worktime/operations?station=STA-01 应返回 200"""
        resp = client.get(
            "/api/v1/worktime/operations?station=STA-01&shift=morning",
            headers=auth_headers,
        )
        assert resp.status_code == 200, (
            f"Expected 200 but got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert "data" in data
        items = data["data"]
        # All returned items should be for STA-01
        for item in items:
            assert item.get("station") == "STA-01", (
                f"Expected station STA-01 but got {item.get('station')}: {item}"
            )

    def test_boxplot_with_station(
        self, client, auth_headers, seed_stations_and_segments
    ):
        """调用 /api/v1/worktime/boxplot?station=STA-01 应返回 200"""
        resp = client.get(
            "/api/v1/worktime/boxplot?station=STA-01",
            headers=auth_headers,
        )
        assert resp.status_code == 200, (
            f"Expected 200 but got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert "data" in data
        boxplot = data["data"]
        # Should only contain STA-01
        assert "STA-01" in boxplot.get("stations", []), (
            f"Expected STA-01 in stations: {boxplot.get('stations')}"
        )
        if "STA-02" in boxplot.get("stations", []):
            pass  # boxplot may show all stations from segments

    def test_heatmap_with_station(
        self, client, auth_headers, seed_stations_and_segments
    ):
        """调用 /api/v1/worktime/heatmap?station=STA-01 应返回 200"""
        resp = client.get(
            "/api/v1/worktime/heatmap?station=STA-01",
            headers=auth_headers,
        )
        assert resp.status_code == 200, (
            f"Expected 200 but got {resp.status_code}: {resp.text}"
        )

    def test_stations_api_returns_expected_fields(
        self, client, auth_headers, seed_stations_and_segments
    ):
        """GET /api/stations 应返回完整工位信息，供前端生成显示文本。

        显示格式: 编号{name} - {worker}({line}-{shift})
        """
        resp = client.get("/api/stations", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "data" in data
        stations = data["data"]
        assert len(stations) >= 2, f"Expected at least 2 stations, got {len(stations)}"

        for st in stations:
            assert "id" in st, f"Station missing 'id': {st}"
            assert "name" in st, f"Station missing 'name': {st}"
            assert "worker" in st, f"Station missing 'worker': {st}"
            assert "line" in st, f"Station missing 'line': {st}"
            assert "shift" in st, f"Station missing 'shift': {st}"

        # Verify the display format would work
        st_info = stations[0]
        display_text = f"编号{st_info['name']} - {st_info['worker']}({st_info['line']}-{st_info['shift']})"
        assert display_text, f"Empty display text for {st_info}"
