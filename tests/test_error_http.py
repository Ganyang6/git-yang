"""HTTP error handling edge case HTTP route for testing"""

from fastapi.testclient import TestClient


def test_error_http_endpoint(monkeypatch):
    # Ensure test environment so that the /test/error route is registered
    monkeypatch.setenv("ENV", "TEST")
    from app.main import app
    client = TestClient(app)
    resp = client.get("/test/error")
    assert resp.status_code == 418
    data = resp.json()
    assert data.get("code") == 9999
    assert data.get("message") == "test controlled error"
