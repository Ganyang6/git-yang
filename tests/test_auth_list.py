"""Auth list endpoint tests (sanitized user list)."""

from fastapi.testclient import TestClient


def test_auth_list_endpoint(monkeypatch):
    # Enable test mode to register test routes and skip production-only behaviors
    monkeypatch.setenv("ENV", "TEST")
    from app.main import app
    client = TestClient(app)

    # Login as admin to obtain a token
    login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "changeme", "remember": False})
    assert login_resp.status_code == 200
    token = login_resp.json().get("data", {}).get("access_token")
    assert token

    # Access list endpoint with token
    resp = client.get("/api/auth/list", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data.get("data", {}), dict)
    assert "users" in data["data"]
