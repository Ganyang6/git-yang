"""
RED Phase — Report KPI changes field should not be None.

Verifies that /api/reports/kpi returns ``changes`` as a dict (possibly empty)
instead of ``None`` (hardcoded TODO).

Frontend: Reports.vue does NOT consume the ``changes`` field.
Therefore no period-over-period comparison logic is needed; the fix is to
return an empty dict instead of None.

This test:
1. Verifies ``changes`` is a dict (not None)
2. Verifies key presence is stable
"""

import pytest


@pytest.fixture(scope="module")
def auth_headers_local(client):
    """Login with actual admin password from config.yaml (12345678)."""
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "12345678",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_changes_is_dict_not_none(client, seed_data, auth_headers_local):
    """Given seed data, changes field should be a dict (never None)."""
    resp = client.get("/api/reports/kpi", headers=auth_headers_local)
    assert resp.status_code == 200, f"KPI endpoint failed: {resp.text}"
    data = resp.json()["data"]
    assert "changes" in data, "changes key missing from KPI response"
    assert isinstance(data["changes"], dict), (
        f"Expected changes to be a dict, got {type(data['changes']).__name__}: {data['changes']}"
    )
