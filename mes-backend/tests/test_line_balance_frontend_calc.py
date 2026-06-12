"""
✨ RED phase: Verify line-balance & worktime API contracts.

Frontend MUST consume these fields from API responses instead of
recalculating them locally.
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
)


# ── Session-scoped test DB ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_db_url():
    """Create a temp DB and set MES_DB_URL before app starts."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="mes_lb_test_")
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
    # Password from config.yaml admin user hash
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "12345678",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Tests ───────────────────────────────────────────────────────────────

def test_line_balance_full_returns_balance_rate_smooth_index(client, auth_headers):
    """line-balance/full MUST return balanceRate and smoothIndex so the
    frontend does NOT recalculate them from station times."""
    resp = client.get("/api/line-balance/full?line=line1", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json().get("data", {})
    assert "balanceRate" in data, "API must return balanceRate"
    assert "smoothIndex" in data, "API must return smoothIndex"
    # balanceRate should be a number
    br = data["balanceRate"]
    assert isinstance(br, (int, float)), f"balanceRate must be numeric, got {type(br)}"


def test_line_balance_summary_returns_balance_rate_smooth_index(client, auth_headers):
    """line-balance/summary MUST return balanceRate and smoothIndex."""
    resp = client.get("/api/line-balance/summary", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json().get("data", {})
    assert "balanceRate" in data
    assert "smoothIndex" in data


def test_worktime_therblig_detail_returns_standard_time_efficiency(client, auth_headers):
    """worktime/therblig/{id} MUST return standardTime and efficiency."""
    from app.models.database import get_session, WorktimeRecord, TherbligDetail

    db_url = os.environ["MES_DB_URL"]
    session = get_session(db_url)

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

    op_id = record.id

    resp = client.get(f"/api/v1/worktime/therblig/{op_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json().get("data", {})
    assert "standardTime" in data, "API must return standardTime"
    assert "efficiency" in data, "API must return efficiency"
    assert isinstance(data["standardTime"], (int, float)), \
        f"standardTime must be numeric, got {type(data['standardTime'])}"
