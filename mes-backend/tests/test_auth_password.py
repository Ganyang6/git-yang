"""
Tests for auth default password security (P0-4).

Verifies that _get_users() does NOT fall back to "changeme" when
DEFAULT_ADMIN_PASSWORD is not configured.
"""

import os
import pytest


def test_no_default_password_fallback(monkeypatch):
    """_get_users() must NOT fall back to 'changeme' when DEFAULT_ADMIN_PASSWORD is unset."""
    # Ensure all env vars that could affect the result are unset
    monkeypatch.delenv("DEFAULT_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("MES_DB_URL", "sqlite:///:memory:")

    # Clear config cache so it reloads fresh
    from app.core.config import load_app_config
    load_app_config.cache_clear()

    from app.api.v1 import auth as auth_mod

    # Clear module-level caches
    auth_mod._jwt_secret_cache = None
    auth_mod._token_expire_cache = None

    users = auth_mod._get_users()
    assert len(users) == 0, (
        f"Expected 0 users when DEFAULT_ADMIN_PASSWORD is not configured, "
        f"got {len(users)}: {users}. "
        "'changeme' fallback is a security issue (P0-4)."
    )


def test_users_returned_when_configured(monkeypatch):
    """When DEFAULT_ADMIN_PASSWORD is set, _get_users() returns the default admin user."""
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "secure-password!")
    monkeypatch.setenv("MES_DB_URL", "sqlite:///:memory:")

    from app.core.config import load_app_config
    load_app_config.cache_clear()

    from app.api.v1 import auth as auth_mod
    auth_mod._jwt_secret_cache = None
    auth_mod._token_expire_cache = None

    users = auth_mod._get_users()
    assert len(users) == 1, (
        f"Expected 1 user when DEFAULT_ADMIN_PASSWORD is set, "
        f"got {len(users)}"
    )
    assert users[0]["username"] == "admin"


def test_login_rate_limiting(monkeypatch, client):
    """Rate limiting must return 429 after too many failed login attempts.

    This test exercises the real rate-limiting path by temporarily disabling
    MES_TEST_MODE, which otherwise bypasses rate limiting.
    """
    # Disable test mode so that the rate-limiting code path is active
    # Use "0" to override conftest.py's default of "1"
    monkeypatch.setenv("MES_TEST_MODE", "0")

    from app.api.v1 import auth as auth_mod
    # Reset rate limiter to a known clean state
    with auth_mod._rate_limit_lock:
        auth_mod._login_fail_tracker.clear()

    # Read the actual rate limit from config (not the module default)
    max_attempts, _ = auth_mod._get_rate_limit_config()

    wrong_creds = {
        "username": "admin",
        "password": "wrong-password",
    }

    # Send failed login attempts up to the configured limit
    for i in range(max_attempts):
        resp = client.post("/api/auth/login", json=wrong_creds)
        assert resp.status_code == 401, (
            f"Attempt {i + 1}: expected 401 (invalid credentials), "
            f"got {resp.status_code}: {resp.text[:200]}"
        )

    # The next attempt should trigger rate-limiting (429)
    resp = client.post("/api/auth/login", json=wrong_creds)
    assert resp.status_code == 429, (
        f"Expected 429 (rate limited), got {resp.status_code}: {resp.text[:200]}"
    )
    detail = resp.json().get("detail", "")
    assert "Too many failed login attempts" in detail, (
        f"Unexpected 429 detail message: {detail}"
    )
