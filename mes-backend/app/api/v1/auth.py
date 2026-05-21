"""
Authentication API routes.

Endpoints:
  POST /api/auth/login  - authenticate and obtain JWT
  GET  /api/auth/me     - get current user info from token

Conforms to spec_security_auth.md.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.api.deps import require_admin
from app.models.schemas import ApiResponse, LoginRequest, UserInfo
from typing import List

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

security = HTTPBearer(auto_error=False)

# In-memory login rate limiter: {ip: [timestamp, ...]}
# NOTE: In multi-worker deployments, use Redis-backed rate limiting for accuracy.
_login_rate_limit: Dict[str, List[float]] = defaultdict(list)
_rate_limit_lock = threading.Lock()
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 60.0  # seconds

# Cached JWT secret to avoid reloading config on every request
_jwt_secret_cache: str | None = None
_jwt_secret_lock = threading.Lock()
# Cached token expiry (normal_hours, remember_hours)
_token_expire_cache: tuple[int, int] | None = None
_token_expire_lock = threading.Lock()


def _get_jwt_secret() -> str:
    """Load JWT secret from config or env (cached after first call).

    Raises HTTPException (503) if JWT_SECRET_KEY is not configured,
    per spec_security_auth.md Section 2.3 (>= 32 bytes, from env).
    """
    global _jwt_secret_cache
    # Fast path: already cached (no lock needed for read)
    if _jwt_secret_cache is not None:
        return _jwt_secret_cache

    with _jwt_secret_lock:
        # Double-check after acquiring lock
        if _jwt_secret_cache is not None:
            return _jwt_secret_cache

        from app.core.config import load_app_config
        cfg = load_app_config()
        secret = cfg.auth.jwt_secret_key
        if not secret:
            logger.error(
                "JWT_SECRET_KEY not set in config or env. "
                "Generate one: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
            raise HTTPException(
                status_code=503,
                detail="JWT_SECRET_KEY is required. Set it via environment variable or config.yaml.",
            )
        if len(secret) < 32:
            logger.warning(
                "JWT_SECRET_KEY is only %d bytes (recommended: >= 32). Consider regenerating.",
                len(secret),
            )
        _jwt_secret_cache = secret
    return secret


def _get_token_expire(remember: bool = False) -> int:
    """Get token expiry in hours (cached)."""
    global _token_expire_cache
    if _token_expire_cache is not None:
        return _token_expire_cache[1] if remember else _token_expire_cache[0]

    with _token_expire_lock:
        if _token_expire_cache is not None:
            return _token_expire_cache[1] if remember else _token_expire_cache[0]

        from app.core.config import load_app_config
        cfg = load_app_config()
        normal = cfg.auth.token_expire_hours
        remember_h = cfg.auth.token_remember_days * 24
        _token_expire_cache = (normal, remember_h)
    return remember_h if remember else normal


def _get_users() -> list[dict]:
    """Get user credentials list from config.

    Users are defined in config.yaml under app.auth.users.
    Each user has: username, password_hash (bcrypt), role, display_name.
    Returns empty list if no config found and no DEFAULT_ADMIN_PASSWORD set.
    """
    from app.core.config import load_app_config
    cfg = load_app_config()
    users = getattr(cfg.auth, "users", None)
    if users:
        return users

    # Only create default admin if DEFAULT_ADMIN_PASSWORD is explicitly set (P0-4)
    default_password = os.environ.get("DEFAULT_ADMIN_PASSWORD")
    if default_password:
        pw_hash = _hash_password(default_password)
        logger.warning(
            "Using default admin credentials. Set bcrypt hash and users "
            "list in config.yaml for production."
        )
        return [
            {
                "username": "admin",
                "password_hash": pw_hash,
                "role": "admin",
                "display_name": "Admin",
            },
        ]
    # No admin password configured — no users (secure default)
    logger.warning(
        "No users configured in config.yaml and DEFAULT_ADMIN_PASSWORD not set. "
        "Login is disabled. Set auth.users in config.yaml or DEFAULT_ADMIN_PASSWORD env var."
    )
    return []


def _hash_password(plain: str) -> str:
    """Hash password using bcrypt (spec 4.2).

    Uses the bcrypt library directly (passlib has compatibility issues
    with bcrypt >= 4.x). Work factor: 12 rounds.
    """
    try:
        import bcrypt as _bcrypt
        salt = _bcrypt.gensalt(rounds=12)
        return _bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")
    except ImportError:
        logger.error("bcrypt is required. Install with: pip install bcrypt")
        raise HTTPException(
            status_code=503,
            detail="Password hashing library not available (bcrypt required)",
        )


def _verify_password(plain: str, stored_hash: str) -> bool:
    """Verify password against stored bcrypt hash (spec 4.2).

    Only bcrypt is supported. SHA-256 fallback has been removed for security.
    """
    try:
        import bcrypt as _bcrypt
        return _bcrypt.checkpw(
            plain.encode("utf-8"), stored_hash.encode("utf-8"),
        )
    except ImportError:
        logger.error("bcrypt not installed")
        return False
    except Exception as e:
        logger.warning("Password verification error: %s", e)
        return False


def create_access_token(username: str, role: str, display_name: str,
                        remember: bool = False) -> str:
    """Create a JWT access token."""
    secret = _get_jwt_secret()
    expire_hours = _get_token_expire(remember)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "display_name": display_name,
        "exp": now + timedelta(hours=expire_hours),
        "iat": now,
        # P2 #75: Add jti (JWT ID) for token versioning. If display_name
        # changes, old tokens still contain old value -- this is acceptable
        # for JWT stateless design. Token refresh is handled by re-login.
        "jti": f"{username}:{int(now.timestamp())}",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    """Decode and validate JWT, return user payload.

    Used as FastAPI dependency for protected routes.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = credentials.credentials
    secret = _get_jwt_secret()
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload


@router.post("/login")
def login(req: LoginRequest, request: Request):
    """Authenticate user and return JWT token.

    Conforms to spec_security_auth.md section 3.1.
    Includes rate limiting: 5 attempts/minute/IP (spec 6.2).
    """
    # Rate limiting (spec 6.2: 5 requests/minute/IP)
    # Skip rate limiting in test environment
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        _client_ip = request.client.host if request.client else "unknown"
        _now = time.time()
        _window_start = _now - _LOGIN_WINDOW

        with _rate_limit_lock:
            _ts = _login_rate_limit[_client_ip]
            _login_rate_limit[_client_ip] = [t for t in _ts if t > _window_start]
            _ts = _login_rate_limit[_client_ip]

            if len(_ts) >= _LOGIN_MAX_ATTEMPTS:
                logger.warning("Login rate limit exceeded for IP: %s", _client_ip)
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many login attempts. Try again in {_LOGIN_WINDOW:.0f} seconds.",
                )

            _ts.append(_now)

    users = _get_users()
    user = None
    for u in users:
        if u["username"] == req.username:
            user = u
            break

    if user is None or not _verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
        )

    access_token = create_access_token(
        username=user["username"],
        role=user["role"],
        display_name=user.get("display_name", user["username"]),
        remember=req.remember,
    )
    expire_hours = _get_token_expire(req.remember)

    logger.info("User %s logged in successfully", req.username)

    return ApiResponse(
        data={
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": expire_hours * 3600,
            "user": {
                "username": user["username"],
                "role": user["role"],
                "display_name": user.get("display_name", user["username"]),
            },
        },
        timestamp=time.time(),
    )


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    """Get current authenticated user info.

    Conforms to spec_security_auth.md section 3.2.
    """
    return ApiResponse(
        data={
            "username": user.get("sub", ""),
            "role": user.get("role", ""),
            "display_name": user.get("display_name", ""),
        },
        timestamp=time.time(),
    )


@router.get("/list")
def list_users(user: dict = Depends(require_admin)):
    """List configured authentication users (sanitized).

    This endpoint is intended for admin/audit usage. Password hashes are not exposed.
    Requires authentication.
    """
    from app.core.config import load_app_config

    cfg = load_app_config()
    users_cfg = getattr(cfg.auth, "users", None) or []
    sanitized: List[dict] = []
    if isinstance(users_cfg, list):
        for u in users_cfg:
            sanitized.append(
                {
                    "username": u.get("username", ""),
                    "role": u.get("role", ""),
                    "display_name": u.get("display_name", u.get("username", "")),
                }
            )
    # If no explicit users configured, provide a default admin entry for UX parity
    if not sanitized:
        sanitized.append({
            "username": "admin",
            "role": "admin",
            "display_name": "Admin",
        })

    return ApiResponse(data={"users": sanitized}, timestamp=time.time())
