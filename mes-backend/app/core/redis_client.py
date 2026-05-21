"""
Redis client wrapper for MES backend.

Provides:
  - RedisClient: async client using redis.asyncio (FastAPI async context)
  - RedisSyncClient: sync client using redis.Redis (Celery workers)
  - Stream producer/consumer helpers
  - Pub/Sub helpers
  - Consumer group management
  - Dead letter queue handling
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import redis.asyncio as aioredis
import redis.exceptions

from app.core.config import RedisConfig

logger = logging.getLogger("mes_backend.redis")


def redact_redis_url(url: str) -> str:
    """Return a Redis URL with the password masked for safe logging.

    Handles formats:
      - redis://:password@host:port/db
      - rediss://:password@host:port/db
      - redis://user:password@host:port/db
    Passwords containing '@' are handled by matching up to the last '@'.
    If no credentials are present, the URL is returned unchanged.
    """
    import re as _re
    m = _re.match(r'^(rediss?://)(.*@)([^@]+)$', url)
    if m:
        scheme, credentials_with_at, host_part = m.groups()
        # credentials_with_at looks like ":password@" or "user:password@"
        # The actual password starts after the last ':' before the trailing '@'
        inner = credentials_with_at[:-1]  # strip trailing '@'
        colon_pos = inner.rfind(':')
        if colon_pos >= 0:
            # There is a ':' indicating password is present
            return f"{scheme}{inner[:colon_pos]}:****@{host_part}"
    return url


# Stream key constants
STREAM_POSE_FRAMES = "mes:pose_frames"
STREAM_ACTION_EVENTS = "mes:action_events"
STREAM_METRICS = "mes:metrics"
STREAM_ANALYSIS_TASKS = "mes:analysis_tasks"
STREAM_ANALYSIS_RESULTS = "mes:analysis_results"
STREAM_SYSTEM_EVENTS = "mes:system_events"
STREAM_DEAD_LETTER = "mes:dead_letter"

# All consumer group definitions: (stream_key, group_name)
ALL_CONSUMER_GROUPS = [
    (STREAM_POSE_FRAMES, "cg:action_classifier"),
    (STREAM_ACTION_EVENTS, "cg:metric_calculator"),
    (STREAM_METRICS, "cg:websocket_pusher"),
    (STREAM_ANALYSIS_TASKS, "cg:celery_worker"),
    (STREAM_ANALYSIS_RESULTS, "cg:ws_notifier"),
    (STREAM_SYSTEM_EVENTS, "cg:sys_monitor"),
]

# Pub/Sub channel constants
CHANNEL_METRICS = "channel:metrics"
CHANNEL_EVENTS = "channel:events"
CHANNEL_ALERTS = "channel:alerts"
CHANNEL_VIDEO_PROGRESS = "channel:video_progress"
CHANNEL_VIDEO_COMMANDS = "channel:video_commands"


class RedisClient:
    """
    Async Redis client for use within FastAPI async context.

    Usage:
        client = RedisClient(config)
        await client.connect()
        await client.publish_frame(camera_id="cam_01", data={...})
        await client.close()
    """

    def __init__(self, config: Optional[RedisConfig] = None) -> None:
        self.config = config or RedisConfig()
        self._pool: Optional[aioredis.Redis] = None
        self._last_error_log: float = 0.0
        self._error_log_interval: float = 10.0

    @property
    def is_connected(self) -> bool:
        return self._pool is not None

    async def connect(self) -> None:
        """Initialize the async Redis connection pool."""
        if self._pool is not None:
            return
        self._pool = aioredis.from_url(
            self.config.url,
            decode_responses=True,
            max_connections=self.config.max_connections,
            socket_connect_timeout=self.config.socket_connect_timeout,
            socket_timeout=self.config.socket_timeout,
        )
        # Verify connection
        try:
            await self._pool.ping()
            logger.info("Redis connected: %s", redact_redis_url(self.config.url))
        except redis.exceptions.ConnectionError as e:
            self._pool = None
            logger.error("Redis connection failed: %s", e)
            raise

    async def close(self) -> None:
        """Close the Redis connection pool."""
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
            logger.info("Redis connection closed")

    async def ensure_connected(self) -> aioredis.Redis:
        """Return the connection pool, attempting reconnect if disconnected.

        Unlike the old synchronous ``_ensure_connected``, this method is
        ``async`` so it can transparently call ``connect()`` when the pool
        has been closed (e.g. during Redis restart or shutdown race).

        Raises ``RuntimeError`` only when the initial reconnect also fails.
        """
        if self._pool is not None:
            return self._pool
        logger.warning("Redis pool is None, attempting reconnect ...")
        await self.connect()
        if self._pool is None:
            raise RuntimeError(
                "Redis client not connected and reconnect failed."
            )
        return self._pool

    # ── Stream Producer ──────────────────────────────────────────────────

    async def publish_frame(self, data: Dict[str, str]) -> Optional[str]:
        """
        Publish a pose frame to the pose_frames stream.

        Args:
            data: Dictionary of field names to string values, following
                  the spec_redis_streams.md format for mes:pose_frames.

        Returns:
            The message ID if successful, None otherwise.
        """
        r = await self.ensure_connected()
        try:
            msg_id = await r.xadd(
                STREAM_POSE_FRAMES,
                data,
                maxlen=self.config.pose_stream_maxlen,
                approximate=True,
            )
            return msg_id
        except redis.exceptions.RedisError as e:
            logger.error("Failed to publish pose frame: %s", e)
            return None

    async def publish_action_event(self, data: Dict[str, str]) -> Optional[str]:
        """Publish an action event to the action_events stream."""
        r = await self.ensure_connected()
        try:
            return await r.xadd(
                STREAM_ACTION_EVENTS,
                data,
                maxlen=self.config.action_stream_maxlen,
                approximate=True,
            )
        except redis.exceptions.RedisError as e:
            logger.error("Failed to publish action event: %s", e)
            return None

    async def publish_metric(self, data: Dict[str, str]) -> Optional[str]:
        """Publish a real-time metric to the metrics stream."""
        r = await self.ensure_connected()
        try:
            return await r.xadd(
                STREAM_METRICS,
                data,
                maxlen=self.config.metrics_stream_maxlen,
                approximate=True,
            )
        except redis.exceptions.RedisError as e:
            logger.error("Failed to publish metric: %s", e)
            return None

    async def publish_analysis_task(self, data: Dict[str, str]) -> Optional[str]:
        """Publish an AI analysis task to the analysis_tasks stream."""
        r = await self.ensure_connected()
        try:
            return await r.xadd(
                STREAM_ANALYSIS_TASKS,
                data,
                maxlen=self.config.analysis_tasks_stream_maxlen,
                approximate=True,
            )
        except redis.exceptions.RedisError as e:
            logger.error("Failed to publish analysis task: %s", e)
            return None

    async def publish_analysis_result(self, data: Dict[str, str]) -> Optional[str]:
        """Publish an analysis result to the analysis_results stream."""
        r = await self.ensure_connected()
        try:
            return await r.xadd(
                STREAM_ANALYSIS_RESULTS,
                data,
                maxlen=self.config.analysis_results_stream_maxlen,
                approximate=True,
            )
        except redis.exceptions.RedisError as e:
            logger.error("Failed to publish analysis result: %s", e)
            return None

    async def publish_system_event(self, data: Dict[str, str]) -> Optional[str]:
        """Publish a system event to the system_events stream."""
        r = await self.ensure_connected()
        try:
            return await r.xadd(
                STREAM_SYSTEM_EVENTS,
                data,
                maxlen=self.config.system_events_stream_maxlen,
                approximate=True,
            )
        except redis.exceptions.RedisError as e:
            logger.error("Failed to publish system event: %s", e)
            return None

    # ── Stream Consumer ──────────────────────────────────────────────────

    async def consume_stream(
        self,
        stream_key: str,
        group: str,
        consumer: str,
        count: int = 100,
        block_ms: int = 5000,
    ) -> List[Dict[str, Any]]:
        """
        Read messages from a consumer group.

        Args:
            stream_key: Redis Stream key (e.g., "mes:pose_frames").
            group: Consumer group name.
            consumer: Consumer instance name.
            count: Maximum number of messages per read.
            block_ms: Blocking timeout in milliseconds (0 = non-blocking).

        Returns:
            List of dicts with "stream", "msg_id", and "fields" keys.
        """
        r = await self.ensure_connected()
        try:
            result = await r.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream_key: ">"},
                count=count,
                block=block_ms,
            )
            messages: List[Dict[str, Any]] = []
            if result:
                for stream_name, msg_list in result:
                    for msg_id, fields in msg_list:
                        messages.append({
                            "stream": stream_name,
                            "msg_id": msg_id,
                            "fields": fields,
                        })
            return messages
        except redis.exceptions.ResponseError as e:
            if "NOGROUP" in str(e):
                logger.warning("Consumer group %s does not exist on %s", group, stream_key)
                # Auto-create consumer group with MKSTREAM and start from "0"
                # to consume all pending messages (including those that arrived
                # before the consumer started).
                try:
                    # id="$" means only consume new messages from this point forward
                    await r.xgroup_create(
                        name=stream_key,
                        groupname=group,
                        id="$",
                        mkstream=True,
                    )
                    logger.info(
                        "Auto-created consumer group %s on %s (id=$)",
                        group, stream_key,
                    )
                except redis.exceptions.ResponseError as cg_err:
                    # Race condition: another consumer may have created it
                    if "BUSYGROUP" not in str(cg_err):
                        logger.error(
                            "Failed to create consumer group %s on %s: %s",
                            group, stream_key, cg_err,
                        )
                return []
        except redis.exceptions.TimeoutError:
            # Normal: XREADGROUP BLOCK timed out with no new messages
            return []
        except redis.exceptions.RedisError as e:
            now = time.time()
            if now - self._last_error_log > self._error_log_interval:
                logger.error(
                    "Redis error consuming stream %s: %s (suppressing similar errors for %ds)",
                    stream_key, e, self._error_log_interval,
                )
                self._last_error_log = now
            return []

    async def ack_message(
        self, stream_key: str, group: str, msg_id: str
    ) -> bool:
        """Acknowledge a message in a consumer group."""
        r = await self.ensure_connected()
        try:
            return await r.xack(stream_key, group, msg_id)
        except redis.exceptions.RedisError as e:
            logger.error("Failed to ack %s in %s: %s", msg_id, stream_key, e)
            return False

    async def pending_count(
        self, stream_key: str, group: str
    ) -> int:
        """Get the number of pending messages in a consumer group."""
        r = await self.ensure_connected()
        try:
            info = await r.xpending(stream_key, group)
            if info:
                return int(info.get("count", 0))
            return 0
        except redis.exceptions.RedisError as e:
            logger.error("Failed to get pending count for %s: %s", stream_key, e)
            return 0

    # ── Consumer Group Management ────────────────────────────────────────

    async def ensure_consumer_groups(self) -> None:
        """
        Create all consumer groups if they don't exist.
        Uses id="0" to consume all existing messages from the start,
        ensuring no data is lost if perception publishes before
        the API container starts its consumers.
        """
        r = await self.ensure_connected()
        for stream_key, group_name in ALL_CONSUMER_GROUPS:
            try:
                await r.xgroup_create(stream_key, group_name, id="0", mkstream=True)
                logger.info("Created consumer group %s on %s", group_name, stream_key)
            except redis.exceptions.ResponseError as e:
                if "BUSYGROUP" in str(e):
                    logger.debug(
                        "Consumer group %s already exists on %s", group_name, stream_key
                    )
                else:
                    raise

    async def reclaim_pending_messages(
        self,
        stream_key: str,
        group: str,
        min_idle_ms: Optional[int] = None,
        consumer: str = "recovery_worker",
    ) -> int:
        """
        Reclaim messages that have been idle too long (PEL recovery).

        Args:
            stream_key: Redis Stream key.
            group: Consumer group name.
            min_idle_ms: Minimum idle time in ms to reclaim. Defaults to config value.
            consumer: Consumer name to reassign messages to.

        Returns:
            Number of messages reclaimed.
        """
        if min_idle_ms is None:
            min_idle_ms = self.config.pel_reclaim_min_idle_ms

        r = await self.ensure_connected()
        try:
            pending = await r.xpending_range(
                stream_key, group, min="-", max="+", count=self.config.pel_max_claim_count
            )
            if not pending:
                return 0

            reclaim_ids = []
            for entry in pending:
                if entry.get("idle", 0) >= min_idle_ms:
                    reclaim_ids.append(entry["message_id"])

            if not reclaim_ids:
                return 0

            result = await r.xclaim(
                stream_key, group, consumer,
                min_idle_time=min_idle_ms,
                message_ids=reclaim_ids,
            )
            reclaimed = len(result) if result else 0
            if reclaimed > 0:
                logger.info(
                    "Reclaimed %d messages from %s/%s (idle > %dms)",
                    reclaimed, stream_key, group, min_idle_ms,
                )
            return reclaimed
        except redis.exceptions.RedisError as e:
            logger.error("Failed to reclaim pending from %s/%s: %s", stream_key, group, e)
            return 0

    # ── Dead Letter Queue ────────────────────────────────────────────────

    async def send_to_dead_letter(
        self,
        original_stream: str,
        msg_id: str,
        fields: Dict[str, str],
        error: str,
        retry_count: int,
    ) -> Optional[str]:
        """
        Send a failed message to the dead letter queue.

        Args:
            original_stream: Original stream key.
            msg_id: Original message ID.
            fields: Original message fields.
            error: Error description.
            retry_count: Number of times processing was attempted.
        """
        r = await self.ensure_connected()
        dead_letter_data = {
            "original_stream": original_stream,
            "original_msg_id": msg_id,
            "error": error,
            "retry_count": str(retry_count),
            "timestamp": str(time.time()),
            **{f"orig_{k}": v for k, v in fields.items()},
        }
        try:
            return await r.xadd(
                STREAM_DEAD_LETTER, dead_letter_data, maxlen=10000, approximate=True,
            )
        except redis.exceptions.RedisError as e:
            logger.error("Failed to write to dead letter queue: %s", e)
            return None

    # ── Pub/Sub ──────────────────────────────────────────────────────────

    async def publish_channel(self, channel: str, message: str) -> bool:
        """Publish a message to a Pub/Sub channel."""
        r = await self.ensure_connected()
        try:
            return await r.publish(channel, message)
        except redis.exceptions.RedisError as e:
            logger.error("Failed to publish to channel %s: %s", channel, e)
            return False

    def listen_channel(self, channel: str) -> AsyncIterator[str]:
        """
        Async generator that yields messages from a Pub/Sub channel.

        Usage:
            async for msg in client.listen_channel("channel:metrics"):
                process(msg)
        """
        if self._pool is None:
            raise RuntimeError("Redis client not connected")

        async def _listener() -> AsyncIterator[str]:
            pubsub = self._pool.pubsub()
            try:
                await pubsub.subscribe(channel)
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        yield message["data"]
                    elif message["type"] == "unsubscribe":
                        break
            except redis.exceptions.RedisError as e:
                logger.error("Pub/Sub listener error on %s: %s", channel, e)
            finally:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except redis.exceptions.RedisError:
                    pass

        return _listener()

    # ── Health Check ─────────────────────────────────────────────────────

    async def ping(self) -> bool:
        """Check if Redis is responsive."""
        r = await self.ensure_connected()
        try:
            return await r.ping()
        except redis.exceptions.RedisError:
            return False


class RedisSyncClient:
    """
    Synchronous Redis client for use in Celery workers and sync contexts.

    Usage:
        client = RedisSyncClient(url="redis://localhost:6379/0")
        client.xadd("mes:pose_frames", {"camera_id": "cam_01", ...})
    """

    def __init__(self, url: str = "", config: RedisConfig | None = None) -> None:
        import redis as sync_redis
        if config is None:
            from app.core.config import load_app_config
            config = load_app_config().redis
        self.config = config
        if not url:
            url = self.config.url
        if not url:
            raise ValueError(
                "redis_url is required - provide via config.yaml, "
                "REDIS_URL env var, or constructor argument"
            )
        self._client = sync_redis.Redis.from_url(
            url, decode_responses=True,
            socket_connect_timeout=self.config.socket_connect_timeout or 5,
            socket_timeout=self.config.socket_timeout or 3,
        )
        self.url = url

    @property
    def client(self):
        """Access the underlying redis.Redis instance."""
        return self._client

    def ping(self) -> bool:
        try:
            return self._client.ping()
        except redis.exceptions.RedisError:
            return False

    def publish(self, channel: str, message: str) -> int | None:
        """Publish a message to a Pub/Sub channel.

        Args:
            channel: Channel name to publish to.
            message: Message string to publish.

        Returns:
            Number of subscribers that received the message, or None on error.
        """
        try:
            return self._client.publish(channel, message)
        except redis.exceptions.RedisError as e:
            logger.error("Failed to publish to channel %s: %s", channel, e)
            return None

    def xadd(self, stream: str, fields: dict, maxlen: int = 1000, approximate: bool = True) -> str | None:
        """Add a message to a Redis Stream.

        Args:
            stream: Stream name.
            fields: Field-value dict for the message.
            maxlen: Approximate max stream length (trimming).
            approximate: Use approximate trimming (default: True).

        Returns:
            Message ID string, or None on error.
        """
        try:
            kw = {"maxlen": maxlen}
            if approximate:
                kw["approximate"] = True
            return self._client.xadd(stream, fields, **kw)
        except redis.exceptions.RedisError as e:
            logger.error("Failed to xadd to stream %s: %s", stream, e)
            return None

    def close(self) -> None:
        self._client.close()
