"""
Tests for GET /api/v1/worktime/recent — standard/efficiency values.

Verifies that the /recent endpoint returns real standard and efficiency
values from the associated WorktimeRecord, not hardcoded zeros.
"""
import os

# Set env BEFORE any app imports
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-at-least-32b!")
os.environ.setdefault("MES_TEST_MODE", "1")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "12345678")

import tempfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.models.database import (
    ProcessSegment, WorktimeRecord,
    get_session, init_db, _engine_cache,
)


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_db_url():
    """Create a temp DB and set MES_DB_URL before app starts."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="mes_recent_worktime_")
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
    """Seed the DB with ProcessSegments both with and without WorktimeRecord association.

    Creates:
      - 2 segments linked to a WorktimeRecord (standard_ms=5000, efficiency=0.8)
      - 1 segment WITHOUT any WorktimeRecord (worktime_record_id=None)
    """
    init_db(db_url=test_db_url, echo=False)
    session = get_session(test_db_url)

    now = datetime.now(timezone.utc)

    # ── Create WorktimeRecord with known standard_ms and efficiency ──
    record = WorktimeRecord(
        operation="assemble",
        station_id="WS-RECENT",
        actual_ms=6250.0,     # 6.25s actual
        standard_ms=5000.0,   # 5.0s standard
        efficiency=0.8,       # 80%
        mod_total=38.0,
        shift="morning",
    )
    session.add(record)
    session.flush()  # populate record.id

    # ── Create ProcessSegments linked to the WorktimeRecord ──
    for i in range(2):
        seg = ProcessSegment(
            camera_id="cam_0",
            station_id="WS-RECENT",
            line="L1",
            action="assemble",
            therblig_symbol="A",
            start_time=now,
            end_time=now,
            duration_ms=3125.0,
            confidence=0.9,
            shift="morning",
            worktime_record_id=record.id,
        )
        session.add(seg)

    # ── Create ProcessSegment WITHOUT worktime_record_id ──
    seg_no_record = ProcessSegment(
        camera_id="cam_0",
        station_id="WS-RECENT",
        line="L1",
        action="reach",
        therblig_symbol="RE",
        start_time=now,
        end_time=now,
        duration_ms=1000.0,
        confidence=0.8,
        shift="morning",
        worktime_record_id=None,
    )
    session.add(seg_no_record)

    session.commit()
    session.close()
    return True


# ── Tests ───────────────────────────────────────────────────────────────

class TestRecentWorktimeStandardEfficiency:
    """Verify /recent endpoint returns real standard/efficiency values."""

    def test_recent_worktime_has_standard_and_efficiency(self, client, auth_headers, seeded_db):
        """Segments linked to a WorktimeRecord should return standard > 0 and efficiency > 0."""
        resp = client.get("/api/v1/worktime/recent?limit=10", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]

        # Filter for the assembly segments we seeded (associated with WorktimeRecord)
        linked_items = [item for item in data if item["operation"] == "assemble"]
        assert len(linked_items) >= 1, (
            f"Expected at least one 'assemble' segment, got: {[i['operation'] for i in data]}"
        )

        for item in linked_items:
            assert item["standard"] > 0, (
                f"Expected standard > 0 for WorktimeRecord-linked segment, got {item['standard']}"
            )
            assert item["efficiency"] > 0, (
                f"Expected efficiency > 0 for WorktimeRecord-linked segment, got {item['efficiency']}"
            )
            # Verify the values match what we seeded
            # standard_ms=5000ms → 5.0s
            assert abs(item["standard"] - 5.0) < 0.01, (
                f"Expected standard≈5.0s, got {item['standard']}"
            )
            # efficiency=0.8 → 80% (the endpoint returns scaled percentage or raw?)
            # Looking at recent endpoint: it returns raw efficiency, not *100
            # The actual endpoint output: "efficiency": 0.0 — it's raw, not percentage
            # So efficiency=0.8 should return 0.8
            assert abs(item["efficiency"] - 0.8) < 0.01, (
                f"Expected efficiency≈0.8, got {item['efficiency']}"
            )

    def test_recent_worktime_no_record_defaults_to_zero(self, client, auth_headers, seeded_db):
        """Segments without a WorktimeRecord should return standard=0 and efficiency=0."""
        resp = client.get("/api/v1/worktime/recent?limit=10", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]

        # Filter for the 'reach' segment (no WorktimeRecord)
        unlinked_items = [item for item in data if item["operation"] == "reach"]
        assert len(unlinked_items) >= 1, (
            f"Expected at least one 'reach' segment, got: {[i['operation'] for i in data]}"
        )

        for item in unlinked_items:
            assert item["standard"] == 0.0, (
                f"Expected standard=0 for unlinked segment, got {item['standard']}"
            )
            assert item["efficiency"] == 0.0, (
                f"Expected efficiency=0 for unlinked segment, got {item['efficiency']}"
            )

    def test_recent_worktime_all_fields_present(self, client, auth_headers, seeded_db):
        """Verify all expected fields are present in recent endpoint response."""
        resp = client.get("/api/v1/worktime/recent?limit=10", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) > 0, "Expected at least one segment"

        expected_fields = {"id", "operation", "station", "actual", "standard", "efficiency"}
        for item in data:
            missing = expected_fields - set(item.keys())
            assert not missing, f"Item {item} missing fields: {missing}"
