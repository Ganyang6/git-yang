"""
Tests for AppError handler dispatch correctness.

Verifies that AppError raises through the AppError handler (not generic 500).
"""

from fastapi.testclient import TestClient


def test_app_error_not_caught_by_generic_handler(monkeypatch):
    """AppError should be caught by the AppError handler, not the generic 500."""
    import importlib

    monkeypatch.setenv("ENV", "TEST")

    # Force reload to pick up the /test/error endpoint registration
    import app.main
    importlib.reload(app.main)

    from app.main import app
    client = TestClient(app)

    resp = client.get("/test/error")
    assert resp.status_code == 418, (
        f"Expected 418 (AppError handler), got {resp.status_code}. "
        "Indicates generic Exception handler is intercepting AppError."
    )
    data = resp.json()
    assert data.get("code") == 9999
    assert data.get("message") == "test controlled error"
    assert data.get("data") is None
