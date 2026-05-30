"""WebSocket endpoint for real-time metric streaming.

Authentication uses a post-connect auth frame (NOT query parameter):
  1. Client connects: ws://host:8000/ws/metrics?station=all
  2. Client sends: {"type": "auth", "token": "<jwt>"}
  3. Server validates and responds: {"type": "auth_ok"} or closes (4001)

This avoids JWT exposure in browser history, server logs, and Referer headers.
Broadcasts metrics from Redis Pub/Sub channel:metrics.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger("mes_backend.websocket")

router = APIRouter()

# Maximum concurrent WebSocket connections to prevent resource exhaustion.
_MAX_WS_CONNECTIONS = 500

# Auth frame must arrive within this timeout after connection.
_AUTH_TIMEOUT_SECONDS = 30.0


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, station_id: str = "all") -> bool:
        """Accept a WebSocket connection if under the limit.

        Returns True if accepted, False if rejected due to limit.
        """
        if len(self.active_connections) >= _MAX_WS_CONNECTIONS:
            logger.warning(
                "WebSocket rejected: connection limit reached (%d)", _MAX_WS_CONNECTIONS
            )
            await websocket.close(code=1013, reason="Too many connections")
            return False
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(
            "WebSocket connected: %s, total connections: %d, station: %s",
            websocket.client.host if websocket.client else "unknown",
            len(self.active_connections),
            station_id,
        )
        return True

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        logger.info(
            "WebSocket disconnected, remaining: %d",
            len(self.active_connections),
        )

    async def broadcast(self, message: str) -> None:
        """Send message to all connected clients."""
        if not self.active_connections:
            return
        dead: Set[WebSocket] = set()
        for ws in self.active_connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        self.active_connections -= dead
        if dead:
            logger.warning("Removed %d dead WebSocket connections", len(dead))

    @property
    def connection_count(self) -> int:
        return len(self.active_connections)


# Singleton connection manager
ws_manager = ConnectionManager()


async def _verify_jwt_token(token: str) -> str | None:
    """Verify a JWT token and return the subject (user_id) or None on failure."""
    if not token:
        return None
    try:
        from app.api.v1.auth import _get_jwt_secret
        import jwt

        secret = _get_jwt_secret()
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        logger.warning("WebSocket auth failed: token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning("WebSocket auth failed: %s", e)
        return None
    except Exception as e:
        logger.error("WebSocket auth error: %s", e)
        return None


@router.websocket("/ws/metrics")
async def websocket_metrics(
    websocket: WebSocket,
    station: str = Query("all", description="Station filter"),
) -> None:
    """
    WebSocket endpoint for real-time metric streaming.

    Connect with: ws://host:8000/ws/metrics?station=all

    After connecting, client MUST send an auth frame within 5 seconds:
        {"type": "auth", "token": "<jwt>"}

    Server responds with {"type": "auth_ok"} on success, or closes (4001).
    This avoids JWT exposure in URLs (browser history, server logs, Referer).
    """
    # Accept connection first (before auth) to allow auth-frame handshake.
    accepted = await ws_manager.connect(websocket, station)
    if not accepted:
        ws_manager.disconnect(websocket)
        return

    # --- Phase 1: wait for auth frame ---
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=_AUTH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("WebSocket auth timeout: no auth frame received")
        await websocket.close(code=4001, reason="Auth timeout")
        ws_manager.disconnect(websocket)
        return
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        return
    except Exception:
        ws_manager.disconnect(websocket)
        return

    # Parse auth frame
    user_id: str | None = None
    try:
        msg = json.loads(raw)
        if msg.get("type") == "auth":
            user_id = await _verify_jwt_token(msg.get("token", ""))
    except (json.JSONDecodeError, TypeError):
        pass

    if user_id is None:
        logger.warning("WebSocket auth rejected: invalid auth frame")
        await websocket.close(code=4001, reason="Authentication failed")
        ws_manager.disconnect(websocket)
        return

    await websocket.send_text(json.dumps({"type": "auth_ok"}))

    # --- Phase 2: normal message loop ---
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            else:
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "subscribe":
                        await websocket.send_text(json.dumps({
                            "type": "subscribed",
                            "station": msg.get("station", "all"),
                        }))
                except json.JSONDecodeError:
                    pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)
        ws_manager.disconnect(websocket)
