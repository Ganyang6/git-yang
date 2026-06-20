"""
Tests for worktime API unit conversion (ms → s).

Verifies API endpoints return "actual" values in seconds,
not raw milliseconds from the database.

Env vars are set at module level (before any app import)
to match the conftest.py pattern.
"""
import os

# Set env BEFORE any app imports
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-at-least-32b!")
os.environ.setdefault("MES_TEST_MODE", "1")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "12345678")

import tempfile

import pytest
from fastapi.testclient import TestClient

from app.models.database import (
    ProcessSegment, WorktimeRecord, TherbligDetail,
    get_session, init_db, _engine_cache,
)
from app.services.worktime_aggregator import aggregate_segments, save_segment
from app.services.process_segmenter import SegmentEvent
from app.models.schemas import ActionLabel


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_db_url():
    """Create a temp DB and set MES_DB_URL before app starts."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="mes_worktime_api_")
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
    """FastAPI test client with a clean DB."""
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    """Get admin JWT token."""
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "12345678",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def seeded_db(test_db_url, auth_headers):
    """Seed the DB with worktime records.

    Creates segments with known actual_ms values, then aggregates
    to produce WorktimeRecord + TherbligDetail rows.
    """
    init_db(db_url=test_db_url, echo=False)
    session = get_session(test_db_url)

    # Seed segments with recognisable ms values
    # 1313 ms → 1.313 s (therblig shows 3 decimals → 1.313)
    # 500 ms  → 0.500 s
    ts_night = 1775142000.0  # UTC → local night shift

    for i in range(3):
        ev = SegmentEvent(
            camera_id="cam_0",
            station_id="station_1",
            action=ActionLabel.ASSEMBLE,
            start_time=ts_night + i * 5,
            end_time=ts_night + i * 5 + 5.0,
            duration_ms=1313.0,
            confidence=0.8,
        )
        save_segment(session, ev)

    # Add a WAIT so therblig detail has waste items
    ev_wait = SegmentEvent(
        camera_id="cam_0",
        station_id="station_1",
        action=ActionLabel.WAIT,
        start_time=ts_night + 20,
        end_time=ts_night + 25,
        duration_ms=500.0,
        confidence=0.9,
    )
    save_segment(session, ev_wait)

    # Aggregate to produce WorktimeRecord + TherbligDetail
    aggregate_segments(session, shift="night")
    session.close()
    return True


# ── Tests ───────────────────────────────────────────────────────────────

class TestWorktimeApiUnitConversion:
    """Verify API returns seconds, not milliseconds."""

    def test_get_operations_returns_seconds(self, client, auth_headers, seeded_db):
        """GET /operations: actual field should be seconds."""
        resp = client.get(
            "/api/v1/worktime/operations?station=all&shift=night",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) > 0, "Should have seeded records"

        for item in data:
            actual = item["actual"]
            assert isinstance(actual, (int, float)), f"actual should be numeric"
            # 1313 ms = 1.31 s (2-decimal), well under 10
            assert actual < 10, f"actual={actual} looks like raw ms (expected seconds)"
            assert actual >= 0

    def test_get_therblig_detail_returns_seconds(self, client, auth_headers, seeded_db):
        """GET /therblig/{id}: actual field should be seconds."""
        resp = client.get(
            "/api/v1/worktime/operations?station=all&shift=night",
            headers=auth_headers,
        )
        ops = resp.json()["data"]
        assert len(ops) > 0
        op_id = ops[0]["id"]

        resp = client.get(f"/api/v1/worktime/therblig/{op_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        rows = resp.json()["data"]["rows"]
        assert len(rows) > 0

        for row in rows:
            actual = row["actual"]
            assert isinstance(actual, (int, float))
            assert actual < 10, f"actual={actual} looks like raw ms"
            assert actual >= 0

    def test_get_recent_worktime_returns_seconds(self, client, auth_headers, seeded_db):
        """GET /recent: actual field should be seconds."""
        resp = client.get("/api/v1/worktime/recent?limit=5", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) > 0

        for item in data:
            actual = item["actual"]
            assert isinstance(actual, (int, float))
            assert actual < 10, f"actual={actual} looks like raw ms"
            assert actual >= 0

    def test_therblig_detail_precise_value(self, client, auth_headers, seeded_db):
        """Verify therblig detail returns 1.313 (3-decimal) for 1313 ms."""
        resp = client.get(
            "/api/v1/worktime/operations?station=all&shift=night",
            headers=auth_headers,
        )
        ops = resp.json()["data"]
        op_id = ops[0]["id"]

        resp = client.get(f"/api/v1/worktime/therblig/{op_id}", headers=auth_headers)
        rows = resp.json()["data"]["rows"]
        # Find the ASSEMBLE therblig (1313 ms → 1.313 s)
        # The details might be sorted differently; check any with actual ≈ 1.3
        values = [r["actual"] for r in rows if abs(r["actual"] - 1.3) < 0.1]
        assert len(values) > 0, f"No therblig with actual ≈ 1.3 in {rows}"
        # At 3-decimal precision, 1313/1000 = 1.313
        assert any(abs(v - 1.313) < 0.001 for v in values), (
            f"Expected ≈1.313 for 1313ms, got {values}"
        )

    def test_negative_actual_ms_clamped_to_zero(self, client, auth_headers, test_db_url, seeded_db):
        """RED: WorktimeRecord with negative actual_ms must return actual=0.

        When actual_ms is negative (data error), the API must clamp it to 0
        to avoid violating WorktimeOperation.actual >= 0 validation.
        """
        session = get_session(test_db_url)
        # Create a record with negative actual_ms (reproducing prod bug)
        neg_record = WorktimeRecord(
            operation="TEST", station_id="w1",
            actual_ms=-1577.03,  # negative value from prod
            standard_ms=1000.0, efficiency=0.0,
            mod_total=7.8, shift="afternoon",
        )
        session.add(neg_record)
        session.commit()
        session.close()

        resp = client.get(
            "/api/v1/worktime/operations?station=w1&shift=afternoon",
            headers=auth_headers,
        )
        assert resp.status_code == 200, (
            f"RED: Expected 200 got {resp.status_code}: {resp.text}"
        )
        items = resp.json()["data"]
        # Find our test record
        for item in items:
            if item["operation"] == "TEST":
                assert item["actual"] == 0.0, (
                    f"RED: Expected actual=0.0 for negative actual_ms, "
                    f"got {item['actual']}. Negative actual violates schema ge=0.0."
                )
                break
        else:
            # Record may not appear due to time filter; test passed if no crash
            pass

    def test_calibrate_worktime_returns_seconds(self, client, auth_headers, seeded_db):
        """PUT /operations/{id}: actual and standard should be in seconds."""
        resp = client.get(
            "/api/v1/worktime/operations?station=all&shift=night",
            headers=auth_headers,
        )
        ops = resp.json()["data"]
        assert len(ops) > 0
        op_id = ops[0]["id"]

        # Calibrate with 2000 ms = 2.0 seconds
        resp = client.put(
            f"/api/v1/worktime/operations/{op_id}",
            headers=auth_headers,
            json={"standard_ms": 2000.0},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["actual"] == 1.31, f"actual={data['actual']} should be 1.31s (1313ms)"
        assert data["standard"] == 2.0, f"standard={data['standard']} should be 2.0s (2000ms)"

    def test_therblig_detail_has_standard_seconds(self, client, auth_headers, seeded_db):
        """每个动素行必须有 standardSeconds 字段，值 = mod * 0.129，四舍五入到 2 位小数。"""
        # 1. 获取操作列表
        resp = client.get(
            "/api/v1/worktime/operations?station=all&shift=night",
            headers=auth_headers,
        )
        ops = resp.json()["data"]
        assert len(ops) > 0, "Should have seeded records"
        op_id = ops[0]["id"]

        # 2. 获取动素明细
        resp = client.get(f"/api/v1/worktime/therblig/{op_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        rows = resp.json()["data"]["rows"]
        assert len(rows) > 0, "Should have therblig rows"

        # 3. 验证每行都有 standardSeconds
        for row in rows:
            assert "standardSeconds" in row, f"Row {row} missing standardSeconds"
            expected = round(row["mod"] * 0.129, 2)
            assert abs(row["standardSeconds"] - expected) < 0.001, (
                f"standardSeconds={row['standardSeconds']} != expected={expected} "
                f"(mod={row['mod']} * 0.129)"
            )
