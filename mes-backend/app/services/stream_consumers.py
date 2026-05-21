"""Redis Stream consumers for the MES backend.

Implements background tasks that consume from Redis Streams, process
messages, and produce downstream events/metrics.

Consumers:
    PoseFrameConsumer  -> mes:pose_frames   (group: cg:action_classifier)
    ActionEventConsumer -> mes:action_events (group: cg:metric_calculator)
    MetricAggregator    -> orchestrates metric computation and publishing

Each consumer runs as an asyncio background task within the FastAPI
event loop and can be started / stopped independently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.redis_client import (
    CHANNEL_METRICS,
    STREAM_ACTION_EVENTS,
    STREAM_POSE_FRAMES,
    RedisClient,
)

logger = logging.getLogger("mes_backend.consumers")


def _get_shift_from_timestamp(ts: float) -> str:
    """Determine shift name from epoch timestamp.

    Factory shift schedule (UTC+8):
      morning:   06:00-14:00 (UTC 22:00-06:00)
      afternoon: 14:00-22:00 (UTC 06:00-14:00)
      night:     22:00-06:00 (UTC 14:00-22:00)
    """
    from datetime import timedelta
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    # Convert to UTC+8 for shift determination
    dt_local = dt + timedelta(hours=8)
    hour = dt_local.hour
    if 6 <= hour < 14:
        return "morning"
    elif 14 <= hour < 22:
        return "afternoon"
    else:
        return "night"


class PoseFrameConsumer:
    """Consumes pose frames from Redis Stream and runs action classification.

    Consumer group: cg:action_classifier
    Stream: mes:pose_frames

    Uses ActionPipeline (sliding window + classifier + segmenter) to
    classify each frame and publish SegmentEvent to mes:action_events
    when a segment is closed.
    """

    def __init__(
        self,
        redis_client: RedisClient,
        consumer_name: str = "worker_pose_classifier",
    ) -> None:
        self._redis = redis_client
        self._consumer = consumer_name
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._processed_ids: set[str] = set()
        self._pipeline = None
        self._failure_counts: Dict[str, int] = {}
        self._MAX_FAILURES = 3
        self._log_interval = 0  # P0-2: Periodic stats log counter
        self._input_count = 0
        self._output_count = 0

    def _get_pipeline(self):
        """Lazy-initialize ActionPipeline (singleton per consumer)."""
        if self._pipeline is None:
            from app.services.process_segmenter import ActionPipeline
            self._pipeline = ActionPipeline()
        return self._pipeline

    async def start(self) -> None:
        """Start the consume loop as a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._consume_loop())
        logger.info("PoseFrameConsumer started: %s", self._consumer)

    async def stop(self) -> None:
        """Stop the consume loop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

        # Flush any open segments on stop
        if self._pipeline is not None:
            try:
                events = self._pipeline.flush_all()
                for evt in events:
                    await self._publish_segment_event(evt)
                if events:
                    logger.info("PoseFrameConsumer flushed %d segments on stop", len(events))
            except Exception as exc:
                logger.error("Error flushing segments on stop: %s", exc)
        logger.info("PoseFrameConsumer stopped")

    async def _consume_loop(self) -> None:
        """Main consume loop using blocking XREADGROUP."""
        # _log_interval initialized as self._log_interval in __init__
        while self._running:
            try:
                messages = await self._redis.consume_stream(
                    stream_key=STREAM_POSE_FRAMES,
                    group="cg:action_classifier",
                    consumer=self._consumer,
                    count=10,
                    block_ms=5000,
                )
                for msg in messages:
                    await self._process_message(msg)
                # P0-2: Log conversion stats every ~100 iterations
                self._log_interval += 1
                if self._log_interval % 100 == 0 and self._input_count > 0:
                    conversion = round(self._output_count / self._input_count * 100, 1)
                    logger.info(
                        "P0-2 PoseFrameConsumer stats: input=%d output=%d conversion=%.1f%%",
                        self._input_count, self._output_count, conversion,
                    )
            except asyncio.CancelledError:
                break
            except RuntimeError as exc:
                if "not connected" in str(exc):
                    logger.warning("PoseFrameConsumer: Redis disconnected, stopping")
                    break
                logger.error("PoseFrameConsumer error: %s", exc, exc_info=True)
                await asyncio.sleep(1)
            except Exception as exc:
                logger.error("PoseFrameConsumer error: %s", exc, exc_info=True)
                await asyncio.sleep(1)

    async def _process_message(self, msg: Dict[str, Any]) -> None:
        """Process a single pose-frame message through the ActionPipeline."""
        stream: str = msg["stream"]
        msg_id: str = msg["msg_id"]
        fields: Dict[str, str] = msg["fields"]

        # Deduplication
        frame_id = fields.get("frame_id", "")
        if frame_id in self._processed_ids:
            await self._redis.ack_message(stream, "cg:action_classifier", msg_id)
            return
        self._processed_ids.add(frame_id)
        if len(self._processed_ids) > 10_000:
            # Evict oldest 5000 entries instead of clearing all to prevent
            # reprocessing recent frames (P1 #45)
            to_keep = set(list(self._processed_ids)[-5000:])
            self._processed_ids = to_keep

        # P0-10: Handle flush marker from video processing
        if frame_id == '__flush__':
            station_id = fields.get("station_id", "default")
            logger.info(
                "Received flush marker (station=%s) — closing any open segments",
                station_id,
            )
            pipeline = self._get_pipeline()
            events = pipeline.flush_all(station_id=station_id)
            for evt in events:
                await self._publish_segment_event(evt)
            logger.info("Flush produced %d segment event(s)", len(events))
            await self._redis.ack_message(stream, "cg:action_classifier", msg_id)
            return

        # P0-2 FIX: Track input/output stats for conversion rate diagnostics
        # _input_count / _output_count initialized in __init__ (P0-4)
        self._input_count += 1

        try:
            landmarks_json = fields.get("landmarks", "[]")
            landmarks: list[dict[str, Any]] = json.loads(landmarks_json)

            # P0-2: Track frames with no landmarks (pose not detected)
            if not landmarks or len(landmarks) == 0:
                logger.debug(
                    "P0-2 drop: frame %s has no landmarks (pose not detected)",
                    frame_id,
                )
                await self._redis.ack_message(stream, "cg:action_classifier", msg_id)
                return

            from app.models.schemas import LandmarkSchema, PoseFrameSchema

            pose_frame = PoseFrameSchema(
                camera_id=fields.get("camera_id", ""),
                timestamp=float(fields.get("timestamp", "0")),
                frame_id=frame_id,
                landmarks=[LandmarkSchema(**lm) for lm in landmarks],
                pose_score=float(fields.get("pose_score", "0")),
            )

            station_id = fields.get("station_id", "default")

            # Parse optional hand data
            hand_landmarks_raw = fields.get("hand_landmarks", "[]")
            hand_features_raw = fields.get("hand_features", "{}")
            hand_features = None
            try:
                parsed_hf = json.loads(hand_features_raw)
                if parsed_hf:
                    hand_features = parsed_hf
            except (json.JSONDecodeError, TypeError):
                pass

            # Run ActionPipeline classification (synchronous, safe in async)
            pipeline = self._get_pipeline()
            event = pipeline.process_frame(
                pose_frame, station_id=station_id,
                hand_features=hand_features,
            )

            if event is not None:
                await self._publish_segment_event(event)
                # P0-2: Track output count
                self._output_count += 1

            await self._redis.ack_message(stream, "cg:action_classifier", msg_id)

        except Exception as exc:
            logger.error("Failed to process frame %s: %s", msg_id, exc)
            # Track failures and discard poison messages (P1 #46)
            self._failure_counts[msg_id] = self._failure_counts.get(msg_id, 0) + 1
            if self._failure_counts[msg_id] >= self._MAX_FAILURES:
                logger.error(
                    "Poison message %s failed %d times, discarding",
                    msg_id, self._failure_counts[msg_id],
                )
                try:
                    await self._redis.ack_message(
                        stream, "cg:action_classifier", msg_id
                    )
                except Exception:
                    pass
                self._failure_counts.pop(msg_id, None)
            # Otherwise, do NOT ack -- message stays in PEL for retry

    async def _publish_segment_event(self, event) -> None:
        """Publish a SegmentEvent to mes:action_events Stream."""
        from app.services.therblig_mapper import map_action_to_therblig

        therblig_mapping = map_action_to_therblig(event.action)
        shift = _get_shift_from_timestamp(event.end_time)

        event_data: Dict[str, str] = {
            "camera_id": event.camera_id,
            "station_id": event.station_id,
            "action": event.action.value,
            "duration_ms": str(event.duration_ms),
            "confidence": str(event.confidence),
            "therblig_symbol": therblig_mapping.symbol.value,
            "therblig_name": therblig_mapping.name,
            "mod_value": str(therblig_mapping.mod_value),
            "is_waste": str(int(therblig_mapping.is_waste)),
            "shift": shift,
            "timestamp": str(event.end_time),
        }

        await self._redis.publish_action_event(event_data)
        logger.debug(
            "Published segment event: station=%s action=%s duration=%.0fms",
            event.station_id, event.action.value, event.duration_ms,
        )


class ActionEventConsumer:
    """Consumes action events and calculates real-time metrics.

    Consumer group: cg:metric_calculator
    Stream: mes:action_events

    On each action event:
    1. Persists the segment to InfluxDB (if available).
    2. Persists the segment to SQLite (process_segments table).
    3. Buffers the segment for running metric computation.
    """

    def __init__(
        self,
        redis_client: RedisClient,
        consumer_name: str = "worker_metric_calculator",
        influxdb_client: Any | None = None,
    ) -> None:
        self._redis = redis_client
        self._influxdb = influxdb_client
        self._consumer = consumer_name
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._segment_buffer: List[Dict[str, Any]] = []
        # P1 #46: Track delivery failure count per message ID
        self._failure_counts: Dict[str, int] = {}
        self._MAX_FAILURES = 5
        # MEMORY.md #7: Count persist failures to detect sustained DB issues
        self._persist_fail_count: int = 0
        self._PERSIST_FAIL_THRESHOLD: int = 50
        # Gap-3: Lazy aggregation — trigger aggregate_segments after N persists
        self._unaggregated_count: int = 0
        # 从全局配置读取聚合阈值（默认 50）
        try:
            from app.core.config import load_app_config
            _cfg = load_app_config()
            self._AGGREGATION_THRESHOLD: int = _cfg.stream_consumer.aggregation_threshold
        except Exception:
            self._AGGREGATION_THRESHOLD: int = 50
        # P0-5: Cached DB session for reuse across events
        self._db_session = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._consume_loop())
        logger.info("ActionEventConsumer started: %s", self._consumer)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        # P0-5: Close cached DB session
        if self._db_session is not None:
            try:
                self._db_session.close()
                self._db_session = None
            except Exception as close_exc:
                logger.warning("Failed to close cached DB session: %s", close_exc)
        logger.info("ActionEventConsumer stopped")

    async def _consume_loop(self) -> None:
        while self._running:
            try:
                messages = await self._redis.consume_stream(
                    stream_key=STREAM_ACTION_EVENTS,
                    group="cg:metric_calculator",
                    consumer=self._consumer,
                    count=10,
                    block_ms=5000,
                )
                for msg in messages:
                    await self._process_message(msg)
            except asyncio.CancelledError:
                break
            except RuntimeError as exc:
                if "not connected" in str(exc):
                    logger.warning("ActionEventConsumer: Redis disconnected, stopping")
                    break
                logger.error("ActionEventConsumer error: %s", exc, exc_info=True)
                await asyncio.sleep(1)
            except Exception as exc:
                logger.error("ActionEventConsumer error: %s", exc, exc_info=True)
                await asyncio.sleep(1)

    async def _process_message(self, msg: Dict[str, Any]) -> None:
        """Process a single action-event message."""
        stream: str = msg["stream"]
        msg_id: str = msg["msg_id"]
        fields: Dict[str, str] = msg["fields"]

        try:
            camera_id = fields.get("camera_id", "")
            station_id = fields.get("station_id", "")
            action = fields.get("action", "")
            duration_ms = float(fields.get("duration_ms", "0"))
            confidence = float(fields.get("confidence", "0"))
            shift = fields.get("shift", "morning")
            therblig_symbol = fields.get("therblig_symbol", "")
            end_time = float(fields.get("timestamp", "0"))

            # Persist to InfluxDB (non-critical, degraded gracefully)
            if (
                self._influxdb is not None
                and getattr(self._influxdb, "is_initialized", False)
            ):
                try:
                    self._influxdb.write_segment_event(
                        camera_id=camera_id,
                        station_id=station_id,
                        action=action,
                        therblig_symbol=therblig_symbol,
                        shift=shift,
                        duration_ms=duration_ms,
                        confidence=confidence,
                    )
                except Exception as influx_exc:
                    logger.warning(
                        "InfluxDB write failed (non-critical): %s", influx_exc
                    )

            # Persist to SQLite via save_segment()
            persist_ok = True
            try:
                self._persist_to_sqlite(
                    camera_id=camera_id,
                    station_id=station_id,
                    action=action,
                    therblig_symbol=therblig_symbol,
                    shift=shift,
                    duration_ms=duration_ms,
                    confidence=confidence,
                    end_time=end_time,
                )
            except Exception as db_exc:
                persist_ok = False
                logger.error(
                    "SQLite persist failed for action event %s (failures=%d/%d): %s",
                    msg_id, self._persist_fail_count, self._PERSIST_FAIL_THRESHOLD, db_exc,
                )
            # Buffer for running metric calculation
            self._segment_buffer.append({
                "action": action,
                "duration_ms": duration_ms,
                "station_id": station_id,
                "confidence": confidence,
                "timestamp": time.time(),
            })

            # Keep buffer bounded
            if len(self._segment_buffer) > 1000:
                self._segment_buffer = self._segment_buffer[-500:]

            if persist_ok:
                await self._redis.ack_message(stream, "cg:metric_calculator", msg_id)
            else:
                self._persist_fail_count += 1
                if self._persist_fail_count >= self._PERSIST_FAIL_THRESHOLD:
                    logger.error(
                        "P1-5: Poison action event %s — discarding after %d persist failures",
                        msg_id, self._persist_fail_count,
                    )
                    await self._redis.ack_message(stream, "cg:metric_calculator", msg_id)
                    self._persist_fail_count = 0
                else:
                    logger.warning(
                        "Not ACKing action event %s due to persist failure (failures=%d/%d); will be retried via PEL reclaim",
                        msg_id, self._persist_fail_count, self._PERSIST_FAIL_THRESHOLD,
                    )

        except Exception as exc:
            logger.error("Failed to process action event %s: %s", msg_id, exc)
            # P1 #46: Track failures and discard poison messages
            self._failure_counts[msg_id] = self._failure_counts.get(msg_id, 0) + 1
            if self._failure_counts[msg_id] >= self._MAX_FAILURES:
                logger.error(
                    "Poison message %s failed %d times, discarding",
                    msg_id, self._failure_counts[msg_id],
                )
                await self._redis.ack_message(
                    stream, "cg:metric_calculator", msg_id
                )
                self._failure_counts.pop(msg_id, None)

    def _persist_to_sqlite(
        self,
        camera_id: str,
        station_id: str,
        action: str,
        therblig_symbol: str,
        shift: str,
        duration_ms: float,
        confidence: float,
        end_time: float,
    ) -> None:
        """Persist an action event to SQLite via save_segment().

        Constructs a SegmentEvent from the Stream fields and delegates
        to the worktime_aggregator.save_segment() function.  DB session
        lifecycle is managed internally (open / commit / close).
        """
        from app.models.schemas import ActionLabel
        from app.services.process_segmenter import SegmentEvent
        from app.services.worktime_aggregator import save_segment
        from app.models.database import get_session

        # Compute start_time from end_time - duration_ms
        start_time = end_time - duration_ms / 1000.0

        try:
            action_enum = ActionLabel(action)
        except ValueError:
            logger.warning("Unknown action label '%s', skipping SQLite persist", action)
            return

        event = SegmentEvent(
            camera_id=camera_id,
            station_id=station_id,
            action=action_enum,
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            confidence=confidence,
        )

        # P0-5: Reuse a single cached DB session instead of creating per event
        if self._db_session is None:
            self._db_session = get_session()
        session = self._db_session
        try:
            save_segment(session, event)
            self._persist_fail_count = 0  # Reset: DB recovered
            # Gap-3: Lazy aggregation — count unaggregated segments
            self._unaggregated_count += 1
            if self._unaggregated_count >= self._AGGREGATION_THRESHOLD:
                self._run_aggregation(session, station_id)
        except Exception as exc:
            self._persist_fail_count += 1
            logger.error(
                "SQLite persist failed (failures=%d/%d): %s: %s",
                self._persist_fail_count, self._PERSIST_FAIL_THRESHOLD,
                type(exc).__name__, exc,
            )
            if self._persist_fail_count == self._PERSIST_FAIL_THRESHOLD:
                logger.error(
                    "SQLite persist failure threshold reached (%d). "
                    "DB may be unavailable or corrupted.",
                    self._persist_fail_count,
                )
            # P0-3: Close dirty session so it doesn't poison the next message
            try:
                session.close()
            except Exception:
                pass
            self._db_session = None
            raise

    def _run_aggregation(self, session, station_id: str | None = None) -> None:
        """Run aggregate_segments() to produce WorktimeRecords.

        Called when _unaggregated_count reaches _AGGREGATION_THRESHOLD.
        Uses the same session that just persisted a segment.  On failure,
        session.rollback() is called to prevent returning a dirty connection
        to the pool, and the counter is NOT reset so aggregation will retry.
        """
        from app.services.worktime_aggregator import aggregate_segments

        try:
            for shift in ("morning", "afternoon", "night"):
                aggregate_segments(session, station_id=station_id, shift=shift)
            self._unaggregated_count = 0
            logger.info(
                "Aggregated segments into WorktimeRecords "
                "(station=%s, all shifts)",
                station_id or "all",
            )
        except Exception as exc:
            logger.error(
                "aggregate_segments() failed, will retry: %s", exc,
            )
            session.rollback()

    def compute_current_metrics(self, station_id: str = "all") -> Dict[str, Any]:
        """Compute real-time metrics from buffered segments.

        Per spec_metrics_formulas.md:
        - HUR = T_effective / T_total
        - Wait ratio = T_wait / T_total
        """
        empty: Dict[str, Any] = {
            "human_utilization": 0.0,
            "wait_ratio": 0.0,
            "current_action": "idle",
            "segment_count": 0,
        }

        if not self._segment_buffer:
            return empty

        segments = self._segment_buffer
        if station_id != "all":
            segments = [s for s in segments if s["station_id"] == station_id]

        if not segments:
            return empty

        total_ms = sum(s["duration_ms"] for s in segments)
        wait_ms = sum(s["duration_ms"] for s in segments if s["action"] == "wait")
        idle_ms = sum(s["duration_ms"] for s in segments if s["action"] == "idle")
        effective_ms = total_ms - wait_ms - idle_ms

        hur = effective_ms / total_ms if total_ms > 0 else 0.0
        wait_ratio = wait_ms / total_ms if total_ms > 0 else 0.0

        # Most recent non-idle action
        current_action = "idle"
        for s in reversed(segments):
            if s["action"] != "idle":
                current_action = s["action"]
                break

        return {
            "human_utilization": round(hur, 4),
            "wait_ratio": round(wait_ratio, 4),
            "current_action": current_action,
            "segment_count": len(segments),
        }


class MetricPublisher:
    """Periodically publishes computed metrics to Redis Stream and Pub/Sub.

    A new metric snapshot is produced every 1 second, written to the
    mes:metrics stream, and broadcast over channel:metrics for WebSocket.
    """

    _BACKOFF_INITIAL: float = 1.0
    _BACKOFF_MAX: float = 30.0
    _BACKOFF_MULTIPLIER: float = 2.0

    def __init__(self, redis_client: RedisClient) -> None:
        self._redis = redis_client
        self._publish_task: Optional[asyncio.Task] = None
        self._running = False
        self._metric_consumer: Optional[MetricAggregator] = None
        self._consecutive_errors: int = 0

    async def start(
        self, metric_consumer: Optional[MetricAggregator] = None
    ) -> None:
        if self._running:
            return
        self._metric_consumer = metric_consumer
        self._running = True
        self._publish_task = asyncio.create_task(self._publish_loop())
        logger.info("MetricPublisher started")

    async def stop(self) -> None:
        self._running = False
        if self._publish_task and not self._publish_task.done():
            self._publish_task.cancel()
            try:
                await self._publish_task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("MetricPublisher stopped")

    async def _publish_loop(self) -> None:
        """Publish metrics every 1 second.

        On consecutive errors the sleep is increased with exponential
        back-off (1s -> 2s -> 4s -> ... -> 30s max) so that a
        disconnected Redis does not cause a tight retry loop.
        A single successful publish resets the back-off.
        """
        backoff: float = self._BACKOFF_INITIAL
        while self._running:
            try:
                await asyncio.sleep(1)
                await self._publish_metrics()
                self._consecutive_errors = 0
                backoff = self._BACKOFF_INITIAL
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if isinstance(exc, RuntimeError) and "not connected" in str(exc):
                    logger.warning("MetricPublisher: Redis disconnected, stopping")
                    break
                self._consecutive_errors += 1
                backoff = min(
                    backoff * self._BACKOFF_MULTIPLIER, self._BACKOFF_MAX
                )
                logger.error(
                    "MetricPublisher error (%d consecutive): %s",
                    self._consecutive_errors,
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(backoff)

    async def _publish_metrics(self) -> None:
        """Read current metrics from the consumer and publish.

        P1 #47: Publish metrics per station_id dynamically instead of
        hardcoded value. Publishes aggregate (station_id=all) plus
        per-station metrics if multiple stations are present.
        """
        if self._metric_consumer is None:
            return

        now = time.time()

        # Collect unique station IDs from buffer
        stations: set[str] = set()
        for seg in self._metric_consumer.action_event_consumer._segment_buffer:
            stations.add(seg.get("station_id", "default"))

        if not stations:
            stations = {"default"}

        # Always publish aggregate metrics
        metrics = self._metric_consumer.action_event_consumer.compute_current_metrics()
        metric_data: Dict[str, str] = {
            "station_id": "all",
            "timestamp": str(now),
            "current_action": metrics["current_action"],
            "segment_duration_ms": "0",
            "human_utilization": str(metrics["human_utilization"]),
            "oee": "0.0",
            "human_machine_sync": "0.0",
            "wait_ratio": str(metrics["wait_ratio"]),
            "line_balance_rate": "0.0",
            "smoothness_index": "0.0",
            "bottleneck_station": "",
            "shift_total_seconds": "28800",
            "shift_effective_seconds": str(
                int(28800 * metrics["human_utilization"])
            ),
        }

        await self._redis.publish_metric(metric_data)
        await self._redis.publish_channel(
            CHANNEL_METRICS, json.dumps(metric_data)
        )

        # Publish per-station metrics if there are multiple stations
        if len(stations) > 1:
            for station_id in stations:
                station_metrics = (
                    self._metric_consumer.action_event_consumer
                    .compute_current_metrics(station_id=station_id)
                )
                station_data: Dict[str, str] = {
                    "station_id": station_id,
                    "timestamp": str(now),
                    "current_action": station_metrics["current_action"],
                    "segment_duration_ms": "0",
                    "human_utilization": str(station_metrics["human_utilization"]),
                    "oee": "0.0",
                    "human_machine_sync": "0.0",
                    "wait_ratio": str(station_metrics["wait_ratio"]),
                    "line_balance_rate": "0.0",
                    "smoothness_index": "0.0",
                    "bottleneck_station": "",
                    "shift_total_seconds": "28800",
                    "shift_effective_seconds": str(
                        int(28800 * station_metrics["human_utilization"])
                    ),
                }
                await self._redis.publish_metric(station_data)
                await self._redis.publish_channel(
                    CHANNEL_METRICS, json.dumps(station_data)
                )


class MetricAggregator:
    """Orchestrates metric computation and publishing.

    Combines ActionEventConsumer and MetricPublisher into a single
    manageable unit that can be started / stopped from the lifespan.
    """

    FLUSH_CHANNEL = "channel:flush_segments"

    def __init__(
        self,
        redis_client: RedisClient,
        influxdb_client: Any | None = None,
        consumer_name: str = "worker_metric_aggregator",
    ) -> None:
        self._redis = redis_client
        self._influxdb = influxdb_client
        self.action_event_consumer = ActionEventConsumer(
            redis_client, "worker_action_calc", influxdb_client
        )
        self.pose_frame_consumer = PoseFrameConsumer(
            redis_client, "worker_pose_frame"
        )
        self._publisher = MetricPublisher(redis_client)
        self._flush_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start PoseFrameConsumer, ActionEventConsumer, and periodic publisher."""
        await self.pose_frame_consumer.start()
        await self.action_event_consumer.start()
        await self._publisher.start(metric_consumer=self)
        # Start flush_segments listener
        self._flush_task = asyncio.create_task(self._flush_listener())

    async def stop(self) -> None:
        """Stop the publisher first, then both consumers."""
        await self._publisher.stop()
        await self.action_event_consumer.stop()
        await self.pose_frame_consumer.stop()
        # Stop flush listener
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except (asyncio.CancelledError, Exception):
                pass

    async def _flush_listener(self) -> None:
        """Subscribe to flush_segments channel and trigger immediate aggregation.

        When a video pipeline completes, command_listener.py publishes a
        flush_segments message.  This listener receives it and calls
        aggregate_segments() for the relevant station.
        """
        import json
        logger = logging.getLogger("mes_backend.consumers")
        pubsub = None
        try:
            pool = await self._redis.ensure_connected()
            pubsub = pool.pubsub()
            await pubsub.subscribe(self.FLUSH_CHANNEL)
            logger.info("Flush listener subscribed to %s", self.FLUSH_CHANNEL)
            while True:
                msg = await pubsub.get_message(timeout=1.0)
                if msg is None or msg["type"] != "message":
                    continue
                try:
                    data = json.loads(msg["data"])
                    station_id = data.get("station_id", "default")
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("Invalid flush msg: %s", exc)
                    continue
                logger.info(
                    "Flush aggregation triggered for station=%s",
                    station_id,
                )
                from app.models.database import get_session
                session = get_session()
                try:
                    for shift in ("morning", "afternoon", "night"):
                        from app.services.worktime_aggregator import aggregate_segments
                        aggregate_segments(session, station_id=station_id, shift=shift)
                    session.commit()
                    logger.info(
                        "Flush aggregation completed for station=%s",
                        station_id,
                    )
                except Exception as exc:
                    session.rollback()
                    logger.error(
                        "Flush aggregation failed for station=%s: %s",
                        station_id, exc,
                    )
                finally:
                    session.close()
        except asyncio.CancelledError:
            logger.info("Flush listener stopped")
        except Exception as exc:
            logger.error("Flush listener error: %s", exc)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(self.FLUSH_CHANNEL)
                    await pubsub.close()
                except Exception:
                    pass
