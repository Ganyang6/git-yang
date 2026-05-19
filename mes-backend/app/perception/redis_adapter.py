"""Redis Streams adapter for the perception process.

The perception process (camera_manager + pose_estimator + hand_estimator) runs
in a separate process/thread and publishes pose frame data to Redis Streams for
backend consumers (action classifier, metric calculator, etc.).

Uses the synchronous Redis client since perception runs outside the FastAPI
async event loop.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from app.core.redis_client import (
    STREAM_ACTION_EVENTS,
    STREAM_POSE_FRAMES,
    STREAM_SYSTEM_EVENTS,
    RedisSyncClient,
    redact_redis_url,
)

logger = logging.getLogger("mes_backend.perception")

# Backpressure threshold: if the PEL of mes:pose_frames exceeds this count
# the producer should consider throttling.
_BACKPRESSURE_WARN_THRESHOLD = 300
_BACKPRESSURE_COOLDOWN_S = 30.0


class PerceptionAdapter:
    """Adapter for perception process to publish frames to Redis Streams.

    Uses sync Redis client since perception runs in a thread/process pool,
    not in the FastAPI async event loop.
    """

    def __init__(self, redis_url: str = "") -> None:
        if not redis_url:
            raise ValueError(
                "redis_url is required - provide via config.yaml, "
                "REDIS_URL env var, or constructor argument"
            )
        self._client = RedisSyncClient(redis_url)
        self._running: bool = False
        self._frame_count: int = 0
        self._last_backpressure_warn: float = 0.0
        self._nogroup_warned: bool = False  # NOGROUP already warned

    # -- Lifecycle -----------------------------------------------------------

    def connect(self) -> bool:
        """Attempt to connect to Redis.

        Returns True if the connection is healthy, False otherwise.
        """
        try:
            ok = self._client.ping()
            if ok:
                self._running = True
                logger.info("PerceptionAdapter connected to Redis at %s", redact_redis_url(self._client.url))
            else:
                logger.warning("PerceptionAdapter ping returned False")
            return ok
        except Exception as exc:
            logger.error("PerceptionAdapter connection failed: %s", exc)
            self._running = False
            return False

    def close(self) -> None:
        """Close the underlying Redis connection."""
        try:
            self._client.close()
            logger.info("PerceptionAdapter closed")
        except Exception as exc:
            logger.error("PerceptionAdapter close error: %s", exc)
        finally:
            self._running = False

    def is_connected(self) -> bool:
        """Return True if the adapter is considered connected."""
        return self._running

    # -- Publishing helpers ---------------------------------------------------

    def _xadd(
        self,
        stream_key: str,
        fields: dict[str, str],
        maxlen: int,
    ) -> bool:
        """Low-level XADD wrapper with error handling."""
        try:
            self._client.client.xadd(
                stream_key,
                fields,
                maxlen=maxlen,
                approximate=True,
            )
            return True
        except Exception as exc:
            logger.error("Failed to XADD to %s: %s", stream_key, exc)
            # Do NOT set self._running = False for a single XADD failure;
            # transient Redis errors should not kill the adapter.
            return False

    # -- Pose frames ---------------------------------------------------------

    def publish_pose_frame(
        self,
        camera_id: str,
        timestamp: float,
        frame_id: str,
        landmarks: list[dict[str, Any]],
        pose_score: float,
        station_id: str = "default",
        landmark_count: int = 33,
        hand_count: int = 0,
        hand_landmarks: list[dict[str, Any]] | None = None,
        hand_features: dict[str, float] | None = None,
    ) -> bool:
        """Publish a single pose frame to mes:pose_frames.

        Args:
            camera_id: Camera identifier, e.g. "cam_01".
            timestamp: Frame capture time as Unix epoch seconds.
            frame_id: Globally unique frame sequence number (20-digit zero-padded).
            landmarks: List of landmark dicts with name, x, y, z, visibility.
            pose_score: MediaPipe detection confidence in [0.0, 1.0].
            station_id: Work station ID, e.g. "WS-01".
            landmark_count: Number of landmarks (Pose 33 / Hand 21 per hand).
            hand_count: Number of detected hands (0, 1, or 2).
            hand_landmarks: Optional list of hand landmark dicts.
            hand_features: Optional dict of hand-derived features (grip_strength, etc.).
        """
        landmarks_json: str = json.dumps(landmarks, separators=(",", ":"))

        fields: dict[str, str] = {
            "camera_id": camera_id,
            "station_id": station_id,
            "timestamp": str(timestamp),
            "frame_id": frame_id,
            "landmark_count": str(landmark_count),
            "pose_score": str(pose_score),
            "hand_count": str(hand_count),
            "landmarks": landmarks_json,
            "hand_landmarks": json.dumps(hand_landmarks or [], separators=(",", ":")),
            "hand_features": json.dumps(hand_features or {}, separators=(",", ":")),
        }

        ok = self._xadd(STREAM_POSE_FRAMES, fields, maxlen=50000)
        # P1-9: _frame_count increment removed — generate_frame_id() owns the counter.
        #       publish_pose_frame() receives an externally-generated frame_id and
        #       must not double-increment.
        return ok

    # -- Action events -------------------------------------------------------

    def publish_action_event(
        self,
        event_id: str,
        camera_id: str,
        station_id: str,
        action: str,
        therblig_symbol: str,
        therblig_name: str,
        start_time: float,
        end_time: float,
        duration_ms: float,
        confidence: float,
        dominant_region: str = "none",
        shift: str = "morning",
    ) -> bool:
        """Publish an action / therblig event to mes:action_events."""
        fields: dict[str, str] = {
            "event_id": event_id,
            "camera_id": camera_id,
            "station_id": station_id,
            "action": action,
            "therblig_symbol": therblig_symbol,
            "therblig_name": therblig_name,
            "start_time": str(start_time),
            "end_time": str(end_time),
            "duration_ms": str(duration_ms),
            "confidence": str(confidence),
            "dominant_region": dominant_region,
            "shift": shift,
        }

        return self._xadd(STREAM_ACTION_EVENTS, fields, maxlen=86400)

    # -- System events -------------------------------------------------------

    def publish_system_event(
        self,
        event_type: str,
        source: str = "perception",
        level: str = "info",
        camera_id: str = "",
        message: str = "",
    ) -> bool:
        """Publish a system event to mes:system_events."""
        ts: float = time.time()

        fields: dict[str, str] = {
            "event_type": event_type,
            "source": source,
            "level": level,
            "camera_id": camera_id,
            "message": message,
            "timestamp": str(ts),
        }

        return self._xadd(STREAM_SYSTEM_EVENTS, fields, maxlen=10000)

    # -- Backpressure --------------------------------------------------------

    def check_backpressure(self) -> bool:
        """Check the PEL on mes:pose_frames.

        Returns True if pending count > 300, indicating downstream consumers
        cannot keep up and the producer should consider throttling.
        """
        now = time.time()

        try:
            info = self._client.client.xpending(STREAM_POSE_FRAMES, "cg:action_classifier")
            if info is None:
                return False

            # redis-py >= 4.0: xpending(group) returns
            # (pending_count, min_id, max_id, [(consumer, count), ...])
            pending_count: int = 0
            if isinstance(info, (list, tuple)):
                pending_count = int(info[0]) if info else 0
            else:
                pending_count = int(getattr(info, "pending", 0))

            if pending_count > _BACKPRESSURE_WARN_THRESHOLD:
                if now - self._last_backpressure_warn >= _BACKPRESSURE_COOLDOWN_S:
                    logger.warning(
                        "Backpressure on %s: %d pending messages (threshold %d)",
                        STREAM_POSE_FRAMES,
                        pending_count,
                        _BACKPRESSURE_WARN_THRESHOLD,
                    )
                    self._last_backpressure_warn = now
                return True

            return False

        except Exception as exc:
            err_msg = str(exc)
            if "NOGROUP" in err_msg or "No such key" in err_msg:
                # Consumer group does not exist yet - downstream consumer
                # (e.g. action_classifier worker) has not started.
                if not self._nogroup_warned:
                    logger.warning(
                        "Consumer group not found on %s (downstream not started). "
                        "Backpressure check will be skipped until the group is created.",
                        STREAM_POSE_FRAMES,
                    )
                    self._nogroup_warned = True
            else:
                logger.error("Failed to check backpressure on %s: %s", STREAM_POSE_FRAMES, exc)
            return False

    # -- Frame ID generation -------------------------------------------------

    def generate_frame_id(self) -> str:
        """Create a unique frame ID that is safe across multiple processes.

        Format: {pid}_{seq}_{timestamp_ms} zero-padded to 32 chars.
        The combination of process ID, sequence number, and timestamp
        guarantees uniqueness even with multiple perception processes.

        Returns:
            A 32-character unique string.
        """
        self._frame_count += 1
        pid = os.getpid()
        ts_ms = int(time.time() * 1000) % 1_000_000
        raw = f"{pid}_{self._frame_count:06d}_{ts_ms:06d}"
        return raw.ljust(32, "0")[:32]
