"""
Tests for wastePct field in GET /api/v1/worktime/operations.

wastePct = non-value-added therblig time / total therblig time * 100.

This is computed from TherbligDetail.is_waste flag.
"""

import os

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def auth_headers_local(client):
    """Overrides conftest auth_headers with "12345678" password."""
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "12345678",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Test helpers ──────────────────────────────────────────────────────


def _get_db_session():
    """Get a session to the test database for seeding data."""
    from app.models.database import get_session
    db_url = os.environ.get("MES_DB_URL", "")
    if not db_url:
        raise RuntimeError("MES_DB_URL must be set before seeding")
    return get_session(db_url)


def _seed_worktime_with_waste(session):
    """Seed a WorktimeRecord with mixed waste/non-waste TherbligDetail rows.

    Creates:
      - 1 WorktimeRecord (id stored in record_id)
      - 3 therblig details: 2 productive (is_waste=False), 1 waste (is_waste=True)

    Returns:
        record_id (int): the seeded WorktimeRecord id
    """
    from app.models.database import TherbligDetail, WorktimeRecord

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
    session.flush()  # populate record.id

    # 2 productive therbligs (is_waste=False)
    session.add_all([
        TherbligDetail(
            worktime_record_id=record.id,
            symbol="A",
            name="assemble",
            mod=30.0,
            actual_ms=4000.0,
            pct=40.0,
            is_waste=False,
        ),
        TherbligDetail(
            worktime_record_id=record.id,
            symbol="R",
            name="reach",
            mod=20.0,
            actual_ms=3000.0,
            pct=30.0,
            is_waste=False,
        ),
        # 1 waste therblig (is_waste=True)
        TherbligDetail(
            worktime_record_id=record.id,
            symbol="U",
            name="wait",
            mod=12.0,
            actual_ms=3000.0,
            pct=30.0,
            is_waste=True,
        ),
    ])
    session.commit()

    # Expected: waste_ms = 3000, total_ms = 10000, wastePct = 30.0
    return record.id


def _seed_worktime_no_waste(session):
    """Seed a WorktimeRecord with only productive (non-waste) TherbligDetail rows.

    Creates:
      - 1 WorktimeRecord
      - 2 productive therblig details (is_waste=False)

    Returns:
        record_id (int): the seeded WorktimeRecord id
    """
    from app.models.database import TherbligDetail, WorktimeRecord

    record = WorktimeRecord(
        operation="inspection",
        station_id="WS-01",
        actual_ms=8000.0,
        standard_ms=7500.0,
        efficiency=0.9375,
        mod_total=58.0,
        shift="morning",
    )
    session.add(record)
    session.flush()

    session.add_all([
        TherbligDetail(
            worktime_record_id=record.id,
            symbol="A",
            name="assemble",
            mod=30.0,
            actual_ms=5000.0,
            pct=62.5,
            is_waste=False,
        ),
        TherbligDetail(
            worktime_record_id=record.id,
            symbol="R",
            name="reach",
            mod=28.0,
            actual_ms=3000.0,
            pct=37.5,
            is_waste=False,
        ),
    ])
    session.commit()

    # Expected: waste_ms = 0, total_ms = 8000, wastePct = 0.0
    return record.id


# ── Test cases ────────────────────────────────────────────────────────


class TestOperationsWastePct:
    """Verify wastePct field is returned correctly in operations list."""

    def test_operations_returns_waste_pct(self, client, auth_headers_local):
        """Seed with waste therbligs, verify wastePct > 0 in response."""
        session = _get_db_session()
        record_id = _seed_worktime_with_waste(session)
        session.close()

        resp = client.get(
            "/api/v1/worktime/operations?station=all&shift=morning",
            headers=auth_headers_local,
        )
        assert resp.status_code == 200

        data = resp.json()["data"]
        assert len(data) > 0

        # Find our seeded operation
        op = next((item for item in data if item["id"] == record_id), None)
        assert op is not None, f"Seeded record id={record_id} not found in response"

        # wastePct must be present and > 0
        assert "wastePct" in op, "wastePct field missing in operations response"
        assert op["wastePct"] > 0, f"Expected wastePct > 0, got {op['wastePct']}"
        # With our seed: waste_ms=3000, total=10000 -> 30.0%
        assert abs(op["wastePct"] - 30.0) < 0.1, (
            f"Expected wastePct ~30.0, got {op['wastePct']}"
        )

    def test_operations_waste_pct_zero_when_no_waste(self, client, auth_headers_local):
        """Seed with only productive therbligs, verify wastePct == 0."""
        session = _get_db_session()
        record_id = _seed_worktime_no_waste(session)
        session.close()

        resp = client.get(
            "/api/v1/worktime/operations?station=all&shift=morning",
            headers=auth_headers_local,
        )
        assert resp.status_code == 200

        data = resp.json()["data"]
        assert len(data) > 0

        op = next((item for item in data if item["id"] == record_id), None)
        assert op is not None, f"Seeded record id={record_id} not found in response"

        assert "wastePct" in op, "wastePct field missing in operations response"
        assert op["wastePct"] == 0.0, (
            f"Expected wastePct == 0.0 (no waste), got {op['wastePct']}"
        )
