"""
AI chat proxy API routes.

Endpoints:
  POST /api/v1/ai/chat  - proxy chat messages to DeepSeek API
  GET  /api/v1/ai/status  - check if AI service is configured
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

# In-memory rate limiter: {username: [timestamp, ...]}
# NOTE: Per-process only. In multi-worker deployments (gunicorn --workers=N),
# each worker maintains its own counter. For distributed rate limiting,
# use Redis-based sliding window (e.g. redis_rate_limit middleware).
_rate_limit_store: Dict[str, List[float]] = defaultdict(list)
_RATE_LIMIT_MAX = 10  # max requests per window
_RATE_LIMIT_WINDOW = 60.0  # seconds
_RATE_LIMIT_CLEANUP_INTERVAL = 300  # clean up stale entries every 5 min
_last_cleanup = 0.0
_rate_limit_lock = threading.Lock()


class ChatMessage(BaseModel):
    role: str = Field(..., pattern=r"^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., max_length=50)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=8192)


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: Optional[dict] = None


def _check_rate_limit(username: str) -> None:
    """Check and enforce per-user rate limit. Raises 429 if exceeded."""
    global _last_cleanup

    now = time.time()

    with _rate_limit_lock:
        # Periodic cleanup of stale user entries to prevent memory leak
        if now - _last_cleanup > _RATE_LIMIT_CLEANUP_INTERVAL:
            window_start = now - _RATE_LIMIT_WINDOW
            stale_keys = [
                k for k, v in _rate_limit_store.items()
                if not v or v[-1] < window_start
            ]
            for k in stale_keys:
                del _rate_limit_store[k]
            _last_cleanup = now

        window_start = now - _RATE_LIMIT_WINDOW
        timestamps = _rate_limit_store[username]

        # Prune old entries
        _rate_limit_store[username] = [t for t in timestamps if t > window_start]
        timestamps = _rate_limit_store[username]

        if len(timestamps) >= _RATE_LIMIT_MAX:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {_RATE_LIMIT_MAX} requests per {_RATE_LIMIT_WINDOW}s",
            )

        timestamps.append(now)


def _get_ai_config():
    """Lazy load AI config to avoid circular imports."""
    from app.core.config import load_app_config
    return load_app_config().ai


@router.post("/chat", response_model=ChatResponse)
async def chat_proxy(
    req: ChatRequest,
    _user: dict = Depends(require_auth),
):
    """
    Proxy chat messages to DeepSeek API.

    Requires JWT authentication. Enforces per-user rate limiting.
    The API key is stored server-side only.
    """
    # Rate limiting
    _check_rate_limit(_user.get("sub", "anonymous"))
    cfg = _get_ai_config()

    if not cfg.api_key:
        raise HTTPException(
            status_code=503,
            detail="AI service not configured: DEEPSEEK_API_KEY not set",
        )

    payload = {
        "model": cfg.model,
        "messages": [{"role": m.role, "content": m.content} for m in req.messages],
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            response = await client.post(
                cfg.api_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {cfg.api_key}",
                },
            )
    except httpx.TimeoutException:
        logger.error("DeepSeek API request timed out (%ds)", cfg.timeout)
        raise HTTPException(status_code=504, detail="AI service timeout")
    except httpx.ConnectError as exc:
        logger.error("DeepSeek API connection error: %s", exc)
        raise HTTPException(status_code=502, detail="AI service unreachable")

    if response.status_code != 200:
        logger.error(
            "DeepSeek API returned %d (no response body logged for security)",
            response.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail="AI service temporarily unavailable",
        )

    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage")

    if not content:
        raise HTTPException(status_code=502, detail="AI returned empty response")

    return ChatResponse(
        content=content,
        model=data.get("model", cfg.model),
        usage=usage,
    )


@router.get("/status")
async def ai_status(_user: dict = Depends(require_auth)):
    """Check whether the AI proxy is configured and ready. Requires auth (S-11)."""
    cfg = _get_ai_config()
    from app.models.schemas import ApiResponse
    return ApiResponse(
        data={"configured": bool(cfg.api_key), "model": cfg.model},
        timestamp=time.time(),
    )
