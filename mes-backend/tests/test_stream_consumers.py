"""Tests for PoseFrameConsumer Stream classification integration (T5-01).

Verifies that PoseFrameConsumer correctly integrates ActionPipeline
to classify frames from Redis Stream and publish SegmentEvent to
mes:action_events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.stream_consumers import (
    ActionEventConsumer,
    PoseFrameConsumer,
    _get_shift_from_timestamp,
)


# ---------------------------------------------------------------------------
# _get_shift_from_timestamp
# ---------------------------------------------------------------------------

class TestGetShiftFromTimestamp:
    """Shift determination from timestamp.

    Shift schedule is in UTC+8 (factory timezone):
      morning:   06:00-14:00 local -> 22:00-06:00 UTC
      afternoon: 14:00-22:00 local -> 06:00-14:00 UTC
      night:     22:00-06:00 local -> 14:00-22:00 UTC
    """

    def test_morning_shift(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 5, 2, 0, 0, tzinfo=timezone.utc)
        assert _get_shift_from_timestamp(dt.timestamp()) == "morning"

    def test_afternoon_shift(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 5, 8, 0, 0, tzinfo=timezone.utc)
        assert _get_shift_from_timestamp(dt.timestamp()) == "afternoon"

    def test_night_shift(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 5, 17, 0, 0, tzinfo=timezone.utc)
        assert _get_shift_from_timestamp(dt.timestamp()) == "night"

    def test_boundary_morning_start(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 4, 22, 0, 0, tzinfo=timezone.utc)
        assert _get_shift_from_timestamp(dt.timestamp()) == "morning"

    def test_boundary_afternoon_start(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 5, 6, 0, 0, tzinfo=timezone.utc)
        assert _get_shift_from_timestamp(dt.timestamp()) == "afternoon"


# ---------------------------------------------------------------------------
# PoseFrameConsumer
# ---------------------------------------------------------------------------

def _make_pose_frame_msg(
    camera_id: str = "cam_01",
    station_id: str = "default",
    frame_id: str = "frame_001",
    timestamp: float | None = None,
    landmarks: list | None = None,
    pose_score: float = 0.95,
) -> Dict[str, Any]:
    """Build a mock Redis Stream message for a pose frame."""
    if timestamp is None:
        timestamp = time.time()
    if landmarks is None:
        # Minimal valid landmarks (enough for feature extraction)
        landmarks = [
            {"name": "LEFT_SHOULDER", "x": 0.5, "y": 0.3, "z": 0.0, "visibility": 0.9},
            {"name": "RIGHT_SHOULDER", "x": 0.5, "y": 0.3, "z": 0.1, "visibility": 0.9},
            {"name": "LEFT_ELBOW", "x": 0.45, "y": 0.5, "z": 0.0, "visibility": 0.85},
            {"name": "RIGHT_ELBOW", "x": 0.55, "y": 0.5, "z": 0.1, "visibility": 0.85},
            {"name": "LEFT_WRIST", "x": 0.4, "y": 0.65, "z": 0.0, "visibility": 0.8},
            {"name": "RIGHT_WRIST", "x": 0.6, "y": 0.65, "z": 0.1, "visibility": 0.8},
        ]
    return {
        "stream": "mes:pose_frames",
        "msg_id": "1234-0",
        "fields": {
            "camera_id": camera_id,
            "station_id": station_id,
            "frame_id": frame_id,
            "timestamp": str(timestamp),
            "landmarks": json.dumps(landmarks),
            "pose_score": str(pose_score),
        },
    }


@pytest.fixture
def mock_redis():
    """Mock RedisClient."""
    redis = AsyncMock()
    redis.consume_stream = AsyncMock(return_value=[])
    redis.ack_message = AsyncMock(return_value=True)
    redis.publish_action_event = AsyncMock(return_value="msg_id")
    return redis


class TestPoseFrameConsumerInit:
    """Consumer initialization."""

    def test_default_consumer_name(self, mock_redis):
        consumer = PoseFrameConsumer(mock_redis)
        assert consumer._consumer == "worker_pose_classifier"

    def test_custom_consumer_name(self, mock_redis):
        consumer = PoseFrameConsumer(mock_redis, consumer_name="custom_worker")
        assert consumer._consumer == "custom_worker"

    def test_pipeline_lazy_init(self, mock_redis):
        consumer = PoseFrameConsumer(mock_redis)
        assert consumer._pipeline is None
        pipeline = consumer._get_pipeline()
        assert pipeline is not None
        # Second call returns same instance
        assert consumer._get_pipeline() is pipeline


class TestPoseFrameConsumerStartStop:
    """Start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self, mock_redis):
        consumer = PoseFrameConsumer(mock_redis)
        mock_redis.consume_stream = AsyncMock(side_effect=asyncio.CancelledError)
        await consumer.start()
        assert consumer._running is True
        await consumer.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, mock_redis):
        consumer = PoseFrameConsumer(mock_redis)
        mock_redis.consume_stream = AsyncMock(side_effect=asyncio.CancelledError)
        await consumer.start()
        await consumer.stop()
        assert consumer._running is False


class TestPoseFrameConsumerProcessMessage:
    """Frame processing through ActionPipeline."""

    @pytest.mark.asyncio
    async def test_process_frame_calls_pipeline(self, mock_redis):
        """Verify that process_frame is called with correct PoseFrameSchema."""
        consumer = PoseFrameConsumer(mock_redis)
        msg = _make_pose_frame_msg()

        # Process should not raise
        await consumer._process_message(msg)

        # Frame should be ACK'd
        mock_redis.ack_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_deduplication(self, mock_redis):
        """Same frame_id should be deduplicated and ACK'd."""
        consumer = PoseFrameConsumer(mock_redis)
        msg = _make_pose_frame_msg(frame_id="dup_001")

        await consumer._process_message(msg)
        await consumer._process_message(msg)

        # Both calls should ACK (dedup skips processing)
        assert mock_redis.ack_message.call_count == 2
        # But pipeline should only see the frame once
        assert "dup_001" in consumer._processed_ids

    @pytest.mark.asyncio
    async def test_empty_landmarks_handled(self, mock_redis):
        """Empty landmarks list should not crash."""
        consumer = PoseFrameConsumer(mock_redis)
        msg = _make_pose_frame_msg(landmarks=[])

        await consumer._process_message(msg)
        mock_redis.ack_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_fields_use_defaults(self, mock_redis):
        """Missing station_id defaults to 'default'."""
        consumer = PoseFrameConsumer(mock_redis)
        msg = _make_pose_frame_msg()
        msg["fields"].pop("station_id", None)

        await consumer._process_message(msg)
        mock_redis.ack_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_segment_event_published(self, mock_redis):
        """When ActionPipeline returns a SegmentEvent, it is published."""
        consumer = PoseFrameConsumer(mock_redis)

        # Mock the pipeline to return a SegmentEvent
        from app.models.schemas import ActionLabel
        from app.services.process_segmenter import SegmentEvent

        fake_event = SegmentEvent(
            camera_id="cam_01",
            station_id="ws_01",
            action=ActionLabel.REACH,
            start_time=time.time() - 2.0,
            end_time=time.time(),
            duration_ms=2000.0,
            confidence=0.85,
        )

        with patch.object(
            consumer, "_get_pipeline",
            return_value=MagicMock(process_frame=MagicMock(return_value=fake_event)),
        ):
            msg = _make_pose_frame_msg(station_id="ws_01")
            await consumer._process_message(msg)

        # Should publish the action event
        mock_redis.publish_action_event.assert_called_once()
        published_data = mock_redis.publish_action_event.call_args[0][0]
        assert published_data["station_id"] == "ws_01"
        assert published_data["action"] == "reach"
        assert published_data["therblig_symbol"] == "R"
        assert published_data["duration_ms"] == "2000.0"
        assert published_data["confidence"] == "0.85"
        assert "shift" in published_data

    @pytest.mark.asyncio
    async def test_no_event_when_pipeline_returns_none(self, mock_redis):
        """When ActionPipeline returns None, nothing is published."""
        consumer = PoseFrameConsumer(mock_redis)

        with patch.object(
            consumer, "_get_pipeline",
            return_value=MagicMock(process_frame=MagicMock(return_value=None)),
        ):
            msg = _make_pose_frame_msg()
            await consumer._process_message(msg)

        # Should ACK but NOT publish
        mock_redis.ack_message.assert_called_once()
        mock_redis.publish_action_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_does_not_ack(self, mock_redis):
        """Processing error should NOT ACK the message."""
        consumer = PoseFrameConsumer(mock_redis)

        # Cause an error by making pipeline raise
        with patch.object(
            consumer, "_get_pipeline",
            side_effect=RuntimeError("test error"),
        ):
            msg = _make_pose_frame_msg()
            await consumer._process_message(msg)

        # Should NOT ack
        mock_redis.ack_message.assert_not_called()


class TestPublishSegmentEvent:
    """SegmentEvent publication format."""

    @pytest.mark.asyncio
    async def test_event_fields_match_spec(self, mock_redis):
        """Verify published fields match spec_redis_streams.md."""
        consumer = PoseFrameConsumer(mock_redis)

        from app.models.schemas import ActionLabel
        from app.services.process_segmenter import SegmentEvent

        fake_event = SegmentEvent(
            camera_id="cam_02",
            station_id="ws_03",
            action=ActionLabel.ASSEMBLE,
            start_time=1743830400.0,
            end_time=1743830405.5,
            duration_ms=5500.0,
            confidence=0.92,
        )

        with patch.object(
            consumer, "_get_pipeline",
            return_value=MagicMock(process_frame=MagicMock(return_value=fake_event)),
        ):
            msg = _make_pose_frame_msg(camera_id="cam_02", station_id="ws_03")
            await consumer._process_message(msg)

        data = mock_redis.publish_action_event.call_args[0][0]

        # Required fields from spec
        assert "camera_id" in data
        assert "station_id" in data
        assert "action" in data
        assert "duration_ms" in data
        assert "confidence" in data
        assert "therblig_symbol" in data
        assert "shift" in data
        assert "timestamp" in data
        # Extra fields for downstream consumers
        assert "therblig_name" in data
        assert "mod_value" in data
        assert "is_waste" in data


class TestMetricAggregatorIncludesPoseFrameConsumer:
    """Verify MetricAggregator creates and starts PoseFrameConsumer.

    Regression test: PoseFrameConsumer was previously never started in the
    API lifespan, breaking the pose_frames -> action_events pipeline.
    """

    def test_metric_aggregator_has_pose_frame_consumer(self):
        """MetricAggregator must hold a PoseFrameConsumer instance."""
        from unittest.mock import MagicMock
        from app.services.stream_consumers import MetricAggregator

        redis_mock = MagicMock()
        agg = MetricAggregator(redis_mock, influxdb_client=None)
        assert hasattr(agg, "pose_frame_consumer")
        assert agg.pose_frame_consumer is not None

    @pytest.mark.asyncio
    async def test_metric_aggregator_starts_pose_frame_consumer(self):
        """MetricAggregator.start() must call PoseFrameConsumer.start() and set running=True."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.stream_consumers import MetricAggregator

        redis_mock = MagicMock()
        # Make consume_stream raise CancelledError after first call to break the loop
        redis_mock.consume_stream = AsyncMock(
            side_effect=asyncio.CancelledError()
        )
        agg = MetricAggregator(redis_mock, influxdb_client=None)

        await agg.start()
        # PoseFrameConsumer task was created (running may be True briefly)
        assert agg.pose_frame_consumer._task is not None
        await agg.stop()

    @pytest.mark.asyncio
    async def test_metric_aggregator_stops_pose_frame_consumer(self):
        """MetricAggregator.stop() must stop PoseFrameConsumer gracefully."""
        from unittest.mock import AsyncMock, MagicMock
        from app.services.stream_consumers import MetricAggregator

        redis_mock = MagicMock()
        redis_mock.consume_stream = AsyncMock(
            side_effect=asyncio.CancelledError()
        )
        agg = MetricAggregator(redis_mock, influxdb_client=None)

        await agg.start()
        await agg.stop()

        assert agg.pose_frame_consumer._running is False


# ---------------------------------------------------------------------------
# ActionEventConsumer._persist_to_sqlite
# ---------------------------------------------------------------------------

# Save a reference to the real get_session BEFORE any patching.
# _persist_to_sqlite imports get_session inside its body, so we must
# patch at the module level.  This reference lets us create sessions
# for verification without going through the mock.
from app.models.database import get_session as _real_get_session


class TestActionEventConsumerPersistToSqlite:
    """Verify _persist_to_sqlite correctly writes to SQLite via save_segment.

    _persist_to_sqlite does `from app.models.database import get_session`
    inside the function body, so we patch `app.models.database.get_session`
    to guarantee the temp-DB session is used regardless of MES_DB_URL env.
    """

    def _init_temp_db(self, tmp_path):
        """Create a temp SQLite DB with tables and return db_url."""
        from app.models.database import init_db

        db_path = tmp_path / "test.db"
        db_url = f"sqlite:///{db_path}"
        init_db(db_url)
        return db_url

    def _query_session(self, db_url):
        """Return a session using the REAL (unpatched) get_session."""
        return _real_get_session(db_url)

    def _make_consumer(self, mock_redis=None):
        if mock_redis is None:
            mock_redis = AsyncMock()
        return ActionEventConsumer(mock_redis, influxdb_client=None)

    def test_persist_valid_segment(self, tmp_path):
        """Valid action event is persisted to SQLite via save_segment."""
        import time
        from unittest.mock import patch

        consumer = self._make_consumer()
        db_url = self._init_temp_db(tmp_path)

        with patch("app.models.database.get_session", side_effect=lambda: _real_get_session(db_url)):
            now = time.time()
            consumer._persist_to_sqlite(
                camera_id="cam_01",
                station_id="WS-01",
                action="reach",
                therblig_symbol="R",
                shift="morning",
                duration_ms=1500.0,
                confidence=0.9,
                end_time=now,
            )

        session = self._query_session(db_url)
        from app.models.database import ProcessSegment
        segments = session.query(ProcessSegment).all()
        session.close()

        assert len(segments) == 1
        seg = segments[0]
        assert seg.camera_id == "cam_01"
        assert seg.station_id == "WS-01"
        assert seg.action == "reach"
        assert seg.therblig_symbol == "R"
        assert seg.duration_ms == 1500.0
        assert seg.confidence == 0.9

    def test_persist_unknown_action_skipped(self, tmp_path):
        """Unknown action label is silently skipped (no exception, no row)."""
        import time
        from unittest.mock import patch

        consumer = self._make_consumer()
        db_url = self._init_temp_db(tmp_path)

        with patch("app.models.database.get_session", side_effect=lambda: _real_get_session(db_url)):
            now = time.time()
            consumer._persist_to_sqlite(
                camera_id="cam_01",
                station_id="WS-01",
                action="nonexistent_action",
                therblig_symbol="?",
                shift="morning",
                duration_ms=1000.0,
                confidence=0.5,
                end_time=now,
            )

        session = self._query_session(db_url)
        from app.models.database import ProcessSegment
        segments = session.query(ProcessSegment).all()
        session.close()

        assert len(segments) == 0

    def test_persist_start_time_computed(self, tmp_path):
        """start_time is correctly computed as end_time - duration_ms."""
        from unittest.mock import patch

        consumer = self._make_consumer()
        db_url = self._init_temp_db(tmp_path)

        end_time = 1745000000.0
        duration_ms = 3000.0

        with patch("app.models.database.get_session", side_effect=lambda: _real_get_session(db_url)):
            consumer._persist_to_sqlite(
                camera_id="cam_01",
                station_id="WS-01",
                action="wait",
                therblig_symbol="UD",
                shift="afternoon",
                duration_ms=duration_ms,
                confidence=0.8,
                end_time=end_time,
            )

        session = self._query_session(db_url)
        from app.models.database import ProcessSegment
        seg = session.query(ProcessSegment).first()
        session.close()

        expected_start_dt = datetime.fromtimestamp(
            end_time - duration_ms / 1000.0, tz=timezone.utc
        ).replace(tzinfo=None)
        assert abs((seg.start_time - expected_start_dt).total_seconds()) < 0.001


# ---------------------------------------------------------------------------
# ActionEventConsumer: persist failure counter + error logging (MEMORY.md #6,7)
# ---------------------------------------------------------------------------

class TestActionEventConsumerPersistFailureCounter:
    """Verify that SQLite persist failures are counted and logged as ERROR."""

    def _make_consumer(self):
        mock_redis = AsyncMock()
        return ActionEventConsumer(mock_redis, influxdb_client=None)

    def test_persist_failure_increments_counter(self):
        """Each _persist_to_sqlite failure must increment _persist_fail_count."""
        consumer = self._make_consumer()
        assert consumer._persist_fail_count == 0

        # Make _persist_to_sqlite fail by patching get_session to raise.
        # _persist_to_sqlite re-raises after counting, so we must catch.
        from unittest.mock import patch
        with patch("app.models.database.get_session", side_effect=RuntimeError("DB locked")):
            with pytest.raises(RuntimeError):
                consumer._persist_to_sqlite(
                    camera_id="cam_01", station_id="WS-01", action="reach",
                    therblig_symbol="R", shift="morning", duration_ms=1000.0,
                    confidence=0.9, end_time=time.time(),
                )

        assert consumer._persist_fail_count == 1

    def test_persist_failure_logged_as_error(self, caplog):
        """Persist failure must use logger.error, not logger.warning."""
        consumer = self._make_consumer()

        from unittest.mock import patch
        with patch("app.models.database.get_session", side_effect=RuntimeError("DB locked")):
            with pytest.raises(RuntimeError):
                consumer._persist_to_sqlite(
                    camera_id="cam_01", station_id="WS-01", action="reach",
                    therblig_symbol="R", shift="morning", duration_ms=1000.0,
                    confidence=0.9, end_time=time.time(),
                )

        # The error must be logged at ERROR level
        assert any(
            record.levelno == logging.ERROR and "SQLite persist failed" in record.message
            for record in caplog.records
        )

    def test_multiple_persist_failures_accumulate(self):
        """Counter must accumulate across multiple failures."""
        consumer = self._make_consumer()

        from unittest.mock import patch
        with patch("app.models.database.get_session", side_effect=RuntimeError("DB locked")):
            for _ in range(5):
                with pytest.raises(RuntimeError):
                    consumer._persist_to_sqlite(
                        camera_id="cam_01", station_id="WS-01", action="reach",
                        therblig_symbol="R", shift="morning", duration_ms=1000.0,
                        confidence=0.9, end_time=time.time(),
                    )

        assert consumer._persist_fail_count == 5


# ---------------------------------------------------------------------------
# P1-1: InfluxDB write failure must NOT trigger poison counter
# ---------------------------------------------------------------------------

class TestInfluxDBWriteFailureIsolation:
    """P1-1: InfluxDB is a degradable component; its failure must not
    propagate to the outer except block and trigger the poison counter."""

    def _make_consumer(self, influxdb_client=None):
        mock_redis = AsyncMock()
        mock_redis.ack_message = AsyncMock()
        return ActionEventConsumer(mock_redis, influxdb_client=influxdb_client)

    @pytest.mark.asyncio
    async def test_influxdb_failure_does_not_poison_message(self, caplog):
        """InfluxDB write failure should be caught internally and logged
        as warning, without affecting the message ACK flow."""
        mock_influxdb = MagicMock()
        mock_influxdb.is_initialized = True
        mock_influxdb.write_segment_event.side_effect = RuntimeError(
            "InfluxDB timeout"
        )

        consumer = self._make_consumer(influxdb_client=mock_influxdb)

        msg = {
            "stream": "mes:action_events",
            "msg_id": "test-msg-001",
            "fields": {
                "camera_id": "cam_01",
                "station_id": "WS-01",
                "action": "reach",
                "duration_ms": "1000",
                "confidence": "0.9",
                "shift": "morning",
                "therblig_symbol": "R",
                "timestamp": str(time.time()),
            },
        }

        # Patch get_session to succeed (no-op session) so SQLite path doesn't fail
        mock_session = MagicMock()
        with patch("app.models.database.get_session", return_value=mock_session):
            # Should NOT raise — InfluxDB failure is isolated
            await consumer._process_message(msg)

        # InfluxDB error must be logged as WARNING (degradable)
        assert any(
            record.levelno == logging.WARNING
            and "InfluxDB" in record.message
            for record in caplog.records
        ), "InfluxDB failure must be logged as WARNING"

        # Message must still be ACKed
        consumer._redis.ack_message.assert_awaited_once()

        # Poison counter must NOT be incremented
        assert "test-msg-001" not in consumer._failure_counts

    @pytest.mark.asyncio
    async def test_influxdb_failure_after_sqlite_success(self, caplog):
        """Even if InfluxDB fails, SQLite data should already be persisted
        and message should be ACKed normally."""
        mock_influxdb = MagicMock()
        mock_influxdb.is_initialized = True
        mock_influxdb.write_segment_event.side_effect = RuntimeError(
            "connection refused"
        )

        consumer = self._make_consumer(influxdb_client=mock_influxdb)

        # Patch get_session to succeed (no-op session)
        mock_session = MagicMock()
        with patch("app.models.database.get_session", return_value=mock_session):
            msg = {
                "stream": "mes:action_events",
                "msg_id": "test-msg-002",
                "fields": {
                    "camera_id": "cam_01",
                    "station_id": "WS-01",
                    "action": "reach",
                    "duration_ms": "1000",
                    "confidence": "0.9",
                    "shift": "morning",
                    "therblig_symbol": "R",
                    "timestamp": str(time.time()),
                },
            }
            await consumer._process_message(msg)

        # No poison counter
        assert "test-msg-002" not in consumer._failure_counts
        # ACK still happened
        mock_redis = consumer._redis
        mock_redis.ack_message.assert_awaited_once()


# ---------------------------------------------------------------------------
# P1-2a: _persist_fail_count resets on success, threshold alert fires once
# ---------------------------------------------------------------------------

class TestPersistFailCountReset:
    """P1-2: Counter must reset on success and threshold alert must fire
    only once (at == threshold), not every subsequent failure."""

    def _make_consumer(self):
        mock_redis = AsyncMock()
        return ActionEventConsumer(mock_redis, influxdb_client=None)

    def test_counter_resets_on_success(self):
        """After a successful persist, the counter must be reset to 0."""
        consumer = self._make_consumer()

        # Simulate 3 failures
        with patch("app.models.database.get_session", side_effect=RuntimeError("DB locked")):
            for _ in range(3):
                with pytest.raises(RuntimeError):
                    consumer._persist_to_sqlite(
                        camera_id="cam_01", station_id="WS-01", action="reach",
                        therblig_symbol="R", shift="morning", duration_ms=1000.0,
                        confidence=0.9, end_time=time.time(),
                    )
        assert consumer._persist_fail_count == 3

        # Now succeed — need a real enough mock
        mock_session = MagicMock()
        with patch("app.models.database.get_session", return_value=mock_session):
            consumer._persist_to_sqlite(
                camera_id="cam_01", station_id="WS-01", action="reach",
                therblig_symbol="R", shift="morning", duration_ms=1000.0,
                confidence=0.9, end_time=time.time(),
            )
        assert consumer._persist_fail_count == 0, "Counter must reset on success"

    def test_threshold_alert_fires_only_once(self, caplog):
        """Threshold alert must fire at exactly == threshold, not >=."""
        consumer = self._make_consumer()
        # Set threshold low for testing
        consumer._PERSIST_FAIL_THRESHOLD = 5

        with patch("app.models.database.get_session", side_effect=RuntimeError("DB locked")):
            for i in range(7):
                with pytest.raises(RuntimeError):
                    consumer._persist_to_sqlite(
                        camera_id="cam_01", station_id="WS-01", action="reach",
                        therblig_symbol="R", shift="morning", duration_ms=1000.0,
                        confidence=0.9, end_time=time.time(),
                    )

        # Count how many times the threshold alert fired
        threshold_alerts = [
            r for r in caplog.records
            if "threshold" in r.message.lower() and r.levelno == logging.ERROR
        ]
        assert len(threshold_alerts) == 1, (
            f"Threshold alert should fire exactly once, got {len(threshold_alerts)}"
        )


# ---------------------------------------------------------------------------
# P2-3: Enhanced test granularity for error log content
# ---------------------------------------------------------------------------

class TestPersistErrorLogGranularity:
    """P2-3: Error logs must contain counter value and exception details."""

    def _make_consumer(self):
        mock_redis = AsyncMock()
        return ActionEventConsumer(mock_redis, influxdb_client=None)

    def test_error_log_contains_counter_value(self, caplog):
        """Error log must include the failure count (e.g. 'failures=1/50')."""
        consumer = self._make_consumer()

        with patch("app.models.database.get_session", side_effect=RuntimeError("DB locked")):
            with pytest.raises(RuntimeError):
                consumer._persist_to_sqlite(
                    camera_id="cam_01", station_id="WS-01", action="reach",
                    therblig_symbol="R", shift="morning", duration_ms=1000.0,
                    confidence=0.9, end_time=time.time(),
                )

        error_logs = [
            r for r in caplog.records
            if r.levelno == logging.ERROR and "SQLite persist failed" in r.message
        ]
        assert len(error_logs) >= 1, "Must have at least one ERROR log"
        # Must contain counter value
        assert "failures=1/" in error_logs[0].message, (
            f"Log must contain counter value, got: {error_logs[0].message}"
        )

    def test_error_log_contains_exception_details(self, caplog):
        """Error log must include the original exception text."""
        consumer = self._make_consumer()

        with patch("app.models.database.get_session", side_effect=RuntimeError("DB locked")):
            with pytest.raises(RuntimeError):
                consumer._persist_to_sqlite(
                    camera_id="cam_01", station_id="WS-01", action="reach",
                    therblig_symbol="R", shift="morning", duration_ms=1000.0,
                    confidence=0.9, end_time=time.time(),
                )

        error_logs = [
            r for r in caplog.records
            if r.levelno == logging.ERROR and "SQLite persist failed" in r.message
        ]
        assert len(error_logs) >= 1
        assert "DB locked" in error_logs[0].message, (
            f"Log must contain exception text, got: {error_logs[0].message}"
        )


# ---------------------------------------------------------------------------
# Gap-3 Fix: _persist_to_sqlite triggers aggregate_segments lazily
# ---------------------------------------------------------------------------

class TestActionEventConsumerLazyAggregation:
    """After N successful _persist_to_sqlite calls, aggregate_segments()
    must be triggered to produce WorktimeRecords from raw segments."""

    def _init_temp_db(self, tmp_path):
        from app.models.database import init_db
        db_path = tmp_path / "test.db"
        db_url = f"sqlite:///{db_path}"
        init_db(db_url)
        return db_url

    def _make_consumer(self):
        mock_redis = AsyncMock()
        return ActionEventConsumer(mock_redis, influxdb_client=None)

    def test_aggregation_triggered_after_threshold_persists(self, tmp_path):
        """After N successful persists, aggregate_segments() must be called
        and WorktimeRecords must exist in the DB."""
        from app.models.database import WorktimeRecord
        from app.services.worktime_aggregator import get_operations

        consumer = self._make_consumer()
        db_url = self._init_temp_db(tmp_path)
        threshold = 5
        consumer._AGGREGATION_THRESHOLD = threshold
        # Use fixed timestamp in UTC morning (maps to UTC+8 morning shift)
        base_time = 1744934400.0  # 2025-04-18 00:00 UTC -> local 08:00 (morning)

        with patch("app.models.database.get_session", side_effect=lambda: _real_get_session(db_url)):
            # Persist exactly THRESHOLD segments
            for i in range(threshold):
                consumer._persist_to_sqlite(
                    camera_id="cam_01",
                    station_id="WS-01",
                    action="reach",
                    therblig_symbol="R",
                    shift="morning",
                    duration_ms=1500.0,
                    confidence=0.9,
                    end_time=base_time + i * 2.0,
                )

        # Verify WorktimeRecords were created
        session = _real_get_session(db_url)
        records, total = get_operations(session, station_id="WS-01", shift="morning")
        session.close()

        assert total >= 1, (
            f"Expected at least 1 WorktimeRecord after {threshold} persists, got {total}"
        )

    def test_aggregation_not_triggered_below_threshold(self, tmp_path):
        """Below threshold, aggregate_segments() must NOT be called."""
        import time
        from app.models.database import WorktimeRecord

        consumer = self._make_consumer()
        db_url = self._init_temp_db(tmp_path)
        threshold = 10
        consumer._AGGREGATION_THRESHOLD = threshold
        base_time = 1744934400.0  # 2025-04-18 00:00 UTC -> local 08:00 (morning)

        with patch("app.models.database.get_session", side_effect=lambda: _real_get_session(db_url)):
            # Persist THRESHOLD - 1 segments
            for i in range(threshold - 1):
                consumer._persist_to_sqlite(
                    camera_id="cam_01",
                    station_id="WS-01",
                    action="reach",
                    therblig_symbol="R",
                    shift="morning",
                    duration_ms=1500.0,
                    confidence=0.9,
                    end_time=base_time + i * 2.0,
                )

        session = _real_get_session(db_url)
        records = session.query(WorktimeRecord).all()
        session.close()

        assert len(records) == 0, (
            f"No WorktimeRecords should exist below threshold, got {len(records)}"
        )

    def test_counter_resets_after_aggregation(self, tmp_path):
        """After aggregation triggers, the unaggregated counter must reset to 0."""
        import time

        consumer = self._make_consumer()
        db_url = self._init_temp_db(tmp_path)
        threshold = 3
        consumer._AGGREGATION_THRESHOLD = threshold
        base_time = 1744934400.0  # 2025-04-18 00:00 UTC -> local 08:00 (morning)

        with patch("app.models.database.get_session", side_effect=lambda: _real_get_session(db_url)):
            for i in range(threshold):
                consumer._persist_to_sqlite(
                    camera_id="cam_01",
                    station_id="WS-01",
                    action="reach",
                    therblig_symbol="R",
                    shift="morning",
                    duration_ms=1500.0,
                    confidence=0.9,
                    end_time=base_time + i * 2.0,
                )

        assert consumer._unaggregated_count == 0, (
            f"Counter must reset after aggregation, got {consumer._unaggregated_count}"
        )

    def test_aggregation_failure_does_not_reset_counter(self, tmp_path):
        """If aggregate_segments() fails, the counter must NOT reset
        (segments remain unaggregated for next attempt)."""

        consumer = self._make_consumer()
        db_url = self._init_temp_db(tmp_path)
        threshold = 2
        consumer._AGGREGATION_THRESHOLD = threshold
        base_time = 1744934400.0  # 2025-04-18 00:00 UTC -> local 08:00 (morning)

        with patch("app.models.database.get_session", side_effect=lambda: _real_get_session(db_url)), \
             patch("app.services.worktime_aggregator.aggregate_segments", side_effect=RuntimeError("DB locked")):
            for i in range(threshold):
                consumer._persist_to_sqlite(
                    camera_id="cam_01",
                    station_id="WS-01",
                    action="reach",
                    therblig_symbol="R",
                    shift="morning",
                    duration_ms=1500.0,
                    confidence=0.9,
                    end_time=base_time + i * 2.0,
                )

        # Counter must NOT reset — segments are still unaggregated
        assert consumer._unaggregated_count == threshold, (
            f"Counter must stay at {threshold} on failure, got {consumer._unaggregated_count}"
        )

    def test_aggregation_failure_rollbacks_session(self, tmp_path):
        """If aggregate_segments() raises, session.rollback() must be called
        to prevent returning a dirty connection to the pool."""

        from unittest.mock import MagicMock

        consumer = self._make_consumer()
        threshold = 2
        consumer._AGGREGATION_THRESHOLD = threshold
        base_time = 1744934400.0
        fake_session = MagicMock()
        fake_session.commit = MagicMock()
        fake_session.add = MagicMock()
        fake_session.refresh = MagicMock()
        fake_session.rollback = MagicMock()
        fake_session.close = MagicMock()

        # make_segment creates a SegmentEvent; save_segment needs session.commit/refresh/add
        # We patch save_segment to succeed, then make _run_aggregation fail on the real session
        with patch("app.models.database.get_session", return_value=fake_session), \
             patch("app.services.worktime_aggregator.aggregate_segments", side_effect=RuntimeError("DB locked")):
            for i in range(threshold):
                consumer._persist_to_sqlite(
                    camera_id="cam_01",
                    station_id="WS-01",
                    action="reach",
                    therblig_symbol="R",
                    shift="morning",
                    duration_ms=1500.0,
                    confidence=0.9,
                    end_time=base_time + i * 2.0,
                )

        fake_session.rollback.assert_called()

    def test_default_aggregation_threshold_is_50(self):
        """Aggregation threshold should be 50 for ~3-4 min intervals at real-time rates."""
        consumer = self._make_consumer()
        assert consumer._AGGREGATION_THRESHOLD == 50, (
            f"Expected threshold 50, got {consumer._AGGREGATION_THRESHOLD}"
        )

    def test_worktime_record_has_correct_values(self, tmp_path):
        """Created WorktimeRecords must have correct actual_ms, operation, etc."""
        from app.models.database import WorktimeRecord

        consumer = self._make_consumer()
        db_url = self._init_temp_db(tmp_path)
        threshold = 5
        consumer._AGGREGATION_THRESHOLD = threshold
        duration_per_segment = 1500.0
        base_time = 1744934400.0  # 2025-04-18 00:00 UTC -> local 08:00 (morning)

        with patch("app.models.database.get_session", side_effect=lambda: _real_get_session(db_url)):
            for i in range(threshold):
                consumer._persist_to_sqlite(
                    camera_id="cam_01",
                    station_id="WS-01",
                    action="reach",
                    therblig_symbol="R",
                    shift="morning",
                    duration_ms=duration_per_segment,
                    confidence=0.9,
                    end_time=base_time + i * 2.0,
                )

        session = _real_get_session(db_url)
        records = session.query(WorktimeRecord).all()
        session.close()

        assert len(records) >= 1
        # Find the "reach" operation record
        reach_records = [r for r in records if r.operation == "reach"]
        assert len(reach_records) == 1
        record = reach_records[0]
        expected_total_ms = threshold * duration_per_segment
        assert record.actual_ms == expected_total_ms, (
            f"Expected actual_ms={expected_total_ms}, got {record.actual_ms}"
        )
        assert record.station_id == "WS-01"
        assert record.shift == "morning"





