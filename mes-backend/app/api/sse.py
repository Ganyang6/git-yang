"""SSE (Server-Sent Events) endpoint for low-frequency event notifications.

Provides /sse/events endpoint for system events, alerts, and notifications.
Subscribes to Redis Pub/Sub channels (channel:events, channel:alerts) and
forwards messages as SSE events to connected clients.  Falls back to
heartbeat-only mode when Redis is unavailable.

Authentication via query parameter token (spec_security_auth.md).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.core.redis_client import CHANNEL_ALERTS, CHANNEL_EVENTS

logger = logging.getLogger("mes_backend.sse")

router = APIRouter()

# Channels to subscribe for SSE event forwarding
_SSE_CHANNELS = (CHANNEL_EVENTS, CHANNEL_ALERTS)

# Heartbeat interval in seconds (must be shorter than any proxy timeout)
_HEARTBEAT_INTERVAL = 15

# SSE 连接上限控制
# 模块级计数器跟踪当前活跃 SSE 连接数
MAX_SSE_CONNECTIONS = 50
_active_sse_connections: int = 0


def _release_sse_connection() -> None:
    """释放一个 SSE 连接槽位。"""
    global _active_sse_connections
    _active_sse_connections -= 1
    logger.debug("SSE connection released, active=%d", _active_sse_connections)


def _get_redis_client(request: Request):
    """Retrieve the RedisClient from app.state (set during lifespan)."""
    return getattr(request.app.state, "redis_client", None)


async def _pubsub_reader(
    redis_client: Any,
    queue: asyncio.Queue[str | None],
) -> None:
    """Background task that reads from Redis Pub/Sub and pushes to a queue.

    Pushes None into the queue when the Pub/Sub connection is lost to signal
    the main generator to fall back to heartbeat-only mode.
    """
    try:
        # Subscribe to all SSE channels via a single pubsub connection
        if redis_client._pool is None:
            await queue.put(None)
            return

        pubsub = redis_client._pool.pubsub()
        await pubsub.subscribe(*_SSE_CHANNELS)
        logger.info("SSE Pub/Sub reader subscribed to %s", _SSE_CHANNELS)

        async for message in pubsub.listen():
            if message["type"] == "message":
                await queue.put(message["data"])
            elif message["type"] in ("unsubscribe", "disconnect"):
                break
    except Exception as exc:
        exc_name = type(exc).__name__
        if exc_name in ("ConnectionError", "ConnectionResetError", "BrokenPipeError"):
            logger.warning("SSE Pub/Sub reader: Redis disconnected (%s)", exc_name)
        else:
            logger.error("SSE Pub/Sub reader error: %s", exc)
    finally:
        # Signal the main generator that Pub/Sub is no longer active
        try:
            await queue.put(None)
        except Exception:
            pass
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:
            pass


@router.get("/sse/events")
async def sse_events(
    request: Request,
    token: str = Query("", description="JWT authentication token"),
    last_event_id: str = Query("", description="Last received event ID for reconnection"),
):
    """
    SSE endpoint for system events and notifications.

    Client connects with EventSource("/sse/events?token=<jwt>") and receives
    JSON event notifications.

    Event types:
    - system: system status changes
    - alert: production alerts (bottleneck, OEE, etc.)
    - analysis: AI analysis results
    - heartbeat: periodic keep-alive
    """
    # SSE 连接上限检查
    global _active_sse_connections
    if _active_sse_connections >= MAX_SSE_CONNECTIONS:
        logger.warning(
            "SSE connection rejected: active=%d >= max=%d",
            _active_sse_connections, MAX_SSE_CONNECTIONS,
        )
        async def conn_limit():
            yield _format_sse("error", {"status": "connection_limit", "message": "Too many SSE connections"})
        return StreamingResponse(
            conn_limit(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    _active_sse_connections += 1
    logger.info("SSE connection accepted, active=%d", _active_sse_connections)

    # JWT authentication (P03)
    if not token:
            yield _format_sse("error", {"status": "auth_required", "message": "Authentication required"})
        return StreamingResponse(
            auth_fail(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    try:
        from app.api.v1.auth import _get_jwt_secret
        import jwt
        secret = _get_jwt_secret()
        jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        async def expired():
            yield _format_sse("error", {"status": "token_expired", "message": "Token expired"})
        return StreamingResponse(
            expired(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
    except Exception as e:
        logger.warning("SSE auth failed: %s", e)
        async def invalid():
            yield _format_sse("error", {"status": "auth_failed", "message": "Invalid token"})
        return StreamingResponse(
            invalid(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    async def event_generator():
        """Generate SSE events from Redis Pub/Sub with heartbeat fallback."""
        event_counter = 0
        last_heartbeat = time.monotonic()
        pubsub_task: asyncio.Task | None = None
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=256)

        # Send initial connection event
        yield _format_sse("connected", {"status": "ok", "time": time.time()})

        redis_client = _get_redis_client(request)
        use_pubsub = redis_client is not None and redis_client.is_connected

        if use_pubsub:
            pubsub_task = asyncio.create_task(
                _pubsub_reader(redis_client, queue),
                name="sse-pubsub-reader",
            )
            logger.info("SSE: Redis Pub/Sub enabled, channels: %s", _SSE_CHANNELS)
        else:
            logger.info("SSE: Redis not available, heartbeat-only mode")

        try:
            while True:
                if await request.is_disconnected():
                    logger.info("SSE client disconnected")
                    break

                now = time.monotonic()

                if use_pubsub and pubsub_task is not None:
                    # Wait for a Pub/Sub message with a timeout so we can
                    # interleave heartbeats and disconnect checks.
                    time_to_next_heartbeat = max(
                        0.0, _HEARTBEAT_INTERVAL - (now - last_heartbeat),
                    )
                    try:
                        raw_msg = await asyncio.wait_for(
                            queue.get(), timeout=time_to_next_heartbeat,
                        )
                    except asyncio.TimeoutError:
                        raw_msg = None  # Timeout: send heartbeat below

                    if raw_msg is not None:
                        # Check if this is the shutdown sentinel
                        if pubsub_task.done():
                            logger.warning("SSE: Pub/Sub reader exited, falling back to heartbeat")
                            use_pubsub = False
                            pubsub_task = None

                        try:
                            data = json.loads(raw_msg) if isinstance(raw_msg, str) else raw_msg
                        except (json.JSONDecodeError, TypeError):
                            data = {"raw": raw_msg}

                        event_type = data.get("type", "system")
                        yield _format_sse(event_type, data)
                        last_heartbeat = time.monotonic()
                        continue

                # Heartbeat (either no Pub/Sub or idle timeout)
                now = time.monotonic()
                if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
                    event_counter += 1
                    yield _format_sse("heartbeat", {
                        "counter": event_counter,
                        "time": time.time(),
                    })
                    last_heartbeat = time.monotonic()

                # Short sleep to avoid busy-looping
                await asyncio.sleep(2)

        except asyncio.CancelledError:
            logger.info("SSE stream cancelled")
        finally:
            # Release SSE connection slot
            _release_sse_connection()
            # Clean up Pub/Sub reader task
            if pubsub_task is not None and not pubsub_task.done():
                pubsub_task.cancel()
                try:
                    await pubsub_task
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse(event_type: str, data: dict, event_id: str = "") -> str:
    """Format data as Server-Sent Events string."""
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


async def publish_sse_event(event_type: str, data: dict, request: Request | None = None) -> bool:
    """Publish an event to Redis Pub/Sub channel:events for SSE clients.

    The SSE endpoint subscribes to this channel and forwards to all
    connected clients.

    Args:
        event_type: Event type string (e.g. "alert", "system", "analysis").
        data: Event payload dict.  A "type" key will be added automatically.
        request: Optional FastAPI Request to retrieve Redis client from.
                 If None, the function is a no-op (caller responsibility).

    Returns:
        True if published successfully, False otherwise.
    """
    redis_client = None
    if request is not None:
        redis_client = _get_redis_client(request)

    if redis_client is None:
        logger.debug("SSE publish skipped: Redis not available")
        return False

    if not redis_client.is_connected:
        logger.debug("SSE publish skipped: Redis not connected")
        return False

    try:
        payload = {"type": event_type, **data}
        message = json.dumps(payload, ensure_ascii=False)
        result = await redis_client.publish_channel(CHANNEL_EVENTS, message)
        if result:
            logger.debug("SSE event published: %s", event_type)
        else:
            logger.debug("SSE event published but no active subscribers: %s", event_type)
        return True
    except Exception as exc:
        logger.warning("SSE publish error: %s", exc)
        return False
