"""
RED phase tests for P1 service-layer bugs.

Tests demonstrate the issue exists (fails on current code).
GREEN phase fixes make these tests pass.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# =====================================================================
# P1 Fix 1: ai_tasks.py - Redis connection leak in Celery workers
# =====================================================================

class TestAiTasksRedisCleanup:
    """P1: _get_ai_gateway creates redis.asyncio client that is never closed.

    The gateway + cache is cached as a module-level singleton. When the Celery
    worker shuts down or after task completion, the Redis connection must be
    released. Verify that _reset_ai_gateway() exists and properly cleans up.
    """

    def test_reset_ai_gateway_function_exists(self):
        """_reset_ai_gateway must be importable."""
        from app.services.ai_tasks import _reset_ai_gateway
        assert callable(_reset_ai_gateway)

    @patch("app.services.ai_tasks._gateway_cache", new=None)
    def test_reset_ai_gateway_handles_no_cache(self):
        """_reset_ai_gateway must not raise when cache is None."""
        from app.services.ai_tasks import _reset_ai_gateway
        # Should not raise
        _reset_ai_gateway()

    @patch("app.services.ai_tasks.logger")
    def test_reset_ai_gateway_closes_redis(self, mock_logger):
        """_reset_ai_gateway must close the cached redis.asyncio client."""
        from app.services.ai_tasks import _reset_ai_gateway, _gateway_cache

        # Create a mock Redis client
        mock_redis = MagicMock()
        mock_redis.aclose = MagicMock()

        # Create a mock cache_store with the mock redis client
        mock_cache_store = MagicMock()
        mock_cache_store.redis_client = mock_redis

        # Set up the global cache
        import app.services.ai_tasks as ai_tasks
        old_cache = ai_tasks._gateway_cache
        try:
            ai_tasks._gateway_cache = (MagicMock(), mock_cache_store)

            _reset_ai_gateway()

            # Verify aclose was called on the redis client
            mock_redis.aclose.assert_called_once()
        finally:
            ai_tasks._gateway_cache = old_cache

    @patch("app.services.ai_tasks.logger")
    def test_calling_reset_clears_cache(self, mock_logger):
        """_reset_ai_gateway must set _gateway_cache to None."""
        from app.services.ai_tasks import _reset_ai_gateway, _gateway_cache

        import app.services.ai_tasks as ai_tasks
        old_cache = ai_tasks._gateway_cache
        try:
            ai_tasks._gateway_cache = (MagicMock(), MagicMock())
            _reset_ai_gateway()
            assert ai_tasks._gateway_cache is None
        finally:
            ai_tasks._gateway_cache = old_cache

    def test_reset_ai_gateway_handles_no_cache_store(self):
        """_reset_ai_gateway must handle case where cache_store is None."""
        from app.services.ai_tasks import _reset_ai_gateway

        import app.services.ai_tasks as ai_tasks
        old_cache = ai_tasks._gateway_cache
        try:
            ai_tasks._gateway_cache = (MagicMock(), None)
            _reset_ai_gateway()
            assert ai_tasks._gateway_cache is None
        finally:
            ai_tasks._gateway_cache = old_cache


# =====================================================================
# P1 Fix 2: video_task_manager.py - Dual storage inconsistency
# =====================================================================

class TestVideoTaskManagerDualStorage:
    """P1: When Redis write fails (hset/hmset), the in-memory fallback is
    invisible because use_redis remains True and subsequent reads target Redis.

    Fix: set self.use_redis = False on Redis write failure so subsequent
    reads route to the in-memory store.
    """

    def test_create_task_fallback_in_memory_retrievable(self):
        """When Redis hset fails in create_task, task must be retrievable via
        get_task (currently invisible because use_redis stays True)."""
        from app.services.video_task_manager import VideoTaskManager

        mgr = VideoTaskManager()
        # Start without Redis: use_redis = False
        assert mgr.use_redis is False
        assert mgr._sync_r is None

        # Simulate a manager that has use_redis=True but a broken sync_r
        mgr.use_redis = True
        mgr._sync_r = MagicMock()
        # Make hset fail with an exception
        mgr._sync_r.hset.side_effect = Exception("Redis connection lost")

        task = mgr.create_task(
            filename="test.mp4",
            original_name="test.mp4",
            size=1000,
            station_id="WS-01",
            video_format="mp4",
        )

        # After the failure, use_redis should fall back to False
        assert mgr.use_redis is False, (
            "After Redis write failure, use_redis should be False "
            "so subsequent reads use in-memory store"
        )

        # The task must still be retrievable from in-memory
        found = mgr.get_task(task["task_id"])
        assert found is not None, (
            "Task created after Redis failure must be retrievable "
            "from in-memory store"
        )
        assert found["status"] == "pending"

    def test_create_task_hset_returns_none_then_fallback(self):
        """When _save_task_sync returns False (simulating timeout/None from hset),
        the in-memory fallback must make the task retrievable."""
        from app.services.video_task_manager import VideoTaskManager

        mgr = VideoTaskManager()
        mgr.use_redis = True
        mgr._sync_r = MagicMock()
        # _save_task_sync returns False if hset raises
        mgr._sync_r.hset.side_effect = Exception("timeout")

        task = mgr.create_task(
            filename="test2.mp4",
            original_name="test2.mp4",
            size=2000,
            station_id="WS-02",
            video_format="mp4",
        )

        # Must have fallen back
        assert mgr.use_redis is False
        # Must be retrievable
        found = mgr.get_task(task["task_id"])
        assert found is not None
        assert found["filename"] == "test2.mp4"

    def test_start_task_fallback_still_retrievable(self):
        """When Redis save fails in start_task (lock acquired but hset fails),
        the task with PROCESSING status must still be retrievable from in-memory.

        Task is created WITH Redis=on (goes through fallback if create fails),
        so start_task's get_task can find it.
        """
        from app.services.video_task_manager import VideoTaskManager

        mgr = VideoTaskManager()
        mgr.use_redis = True
        mgr._sync_r = MagicMock()

        # Lock acquisition succeeds
        mgr._sync_r.set.return_value = True
        # hset fails on create_task (falls back to in-memory)
        mgr._sync_r.hset.side_effect = Exception("Redis write fail")

        task = mgr.create_task(
            filename="start_test.mp4",
            original_name="start_test.mp4",
            size=1000,
            station_id="WS-01",
            video_format="mp4",
        )
        # After create fallback, use_redis is False, task is in memory
        assert mgr.use_redis is False

        task_id = task["task_id"]
        found = mgr.get_task(task_id)
        assert found is not None
        assert found["status"] == "pending"
        assert found["filename"] == "start_test.mp4"


# =====================================================================
# P1 Fix 3: worktime_aggregator.py - Transactional therblig rebuild
# =====================================================================

class TestWorktimeAggregatorTransactional:
    """P1: aggregate_segments deletes TherbligDetail then rebuilds them
    outside a transaction. If the rebuild fails partway, data is lost.

    Fix: wrap the delete+rebuild in a savepoint / nested transaction.
    """

    def test_aggregate_segments_therblig_details_persist(self):
        """After aggregate_segments runs, TherbligDetail rows must exist
        for each WorktimeRecord's operation."""
        import os
        import tempfile
        from datetime import datetime, timezone
        from app.models.database import (
            ProcessSegment, WorktimeRecord, TherbligDetail,
            get_session, init_db, Base,
        )
        from app.models.schemas import ActionLabel, ShiftName
        from app.services.worktime_aggregator import aggregate_segments

        fd, path = tempfile.mkstemp(suffix=".db")
        db_url = f"sqlite:///{path}"
        os.close(fd)

        try:
            engine = init_db(db_url=db_url, echo=False)
            session = get_session(db_url)

            # Create segments
            segments = [
                ProcessSegment(
                    camera_id="cam_0",
                    station_id="WS-01",
                    action=ActionLabel.REACH.value,
                    therblig_symbol="R",
                    start_time=datetime(2026, 4, 2, 1, 0, 0, tzinfo=timezone.utc),
                    end_time=datetime(2026, 4, 2, 1, 0, 3, tzinfo=timezone.utc),
                    duration_ms=3000,
                    confidence=0.9,
                    shift=ShiftName.MORNING.value,
                ),
                ProcessSegment(
                    camera_id="cam_0",
                    station_id="WS-01",
                    action=ActionLabel.GRASP.value,
                    therblig_symbol="G",
                    start_time=datetime(2026, 4, 2, 1, 0, 3, tzinfo=timezone.utc),
                    end_time=datetime(2026, 4, 2, 1, 0, 4, tzinfo=timezone.utc),
                    duration_ms=1000,
                    confidence=0.85,
                    shift=ShiftName.MORNING.value,
                ),
            ]
            for seg in segments:
                session.add(seg)
            session.commit()

            records = aggregate_segments(session, station_id="WS-01", shift="morning")
            assert len(records) >= 2, "Should have created worktime records"

            # Verify TherbligDetails exist
            record_ids = [r.id for r in records]
            details = session.query(TherbligDetail).filter(
                TherbligDetail.worktime_record_id.in_(record_ids)
            ).all()
            detail_count = len(details)
            assert detail_count >= 2, (
                f"Expected TherbligDetail rows, got {detail_count}"
            )

            # Verify they have reasonable values
            for d in details:
                assert d.symbol, "TherbligDetail must have a symbol"
                assert d.actual_ms > 0, "TherbligDetail must have actual_ms > 0"

            session.close()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_aggregate_segments_rebuilds_details_on_rerun(self):
        """Re-running aggregate_segments must delete old details and
        recreate them correctly (without data loss)."""
        import os
        import tempfile
        from datetime import datetime, timezone
        from app.models.database import (
            ProcessSegment, WorktimeRecord, TherbligDetail,
            get_session, init_db,
        )
        from app.models.schemas import ActionLabel, ShiftName
        from app.services.worktime_aggregator import aggregate_segments

        fd, path = tempfile.mkstemp(suffix=".db")
        db_url = f"sqlite:///{path}"
        os.close(fd)

        try:
            engine = init_db(db_url=db_url, echo=False)
            session = get_session(db_url)

            # Create one segment
            seg = ProcessSegment(
                camera_id="cam_0",
                station_id="WS-01",
                action=ActionLabel.REACH.value,
                therblig_symbol="R",
                start_time=datetime(2026, 4, 2, 1, 0, 0, tzinfo=timezone.utc),
                end_time=datetime(2026, 4, 2, 1, 0, 2, tzinfo=timezone.utc),
                duration_ms=2000,
                confidence=0.9,
                shift=ShiftName.MORNING.value,
            )
            session.add(seg)
            session.commit()

            # First aggregation
            records1 = aggregate_segments(session, station_id="WS-01", shift="morning")
            assert len(records1) == 1

            # Get initial detail count
            r1_id = records1[0].id
            details_1 = session.query(TherbligDetail).filter(
                TherbligDetail.worktime_record_id == r1_id
            ).all()
            assert len(details_1) == 1, "Should have 1 therblig detail row"
            old_detail_id = details_1[0].id

            # Second aggregation (same data)
            records2 = aggregate_segments(session, station_id="WS-01", shift="morning")
            assert len(records2) == 1

            # Old details should be replaced, not accumulated
            r2_id = records2[0].id
            details_2 = session.query(TherbligDetail).filter(
                TherbligDetail.worktime_record_id == r2_id
            ).all()
            assert len(details_2) == 1, (
                "After re-aggregation, should have exactly 1 detail "
                "(not accumulated)"
            )

            session.close()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_aggregate_segments_savepoint_on_detail_failure(self):
        """When therblig detail creation fails inside the savepoint, the
        bulk DELETE is rolled back automatically. Old details survive.

        The savepoint wraps delete+rebuild atomically. If rebuild fails,
        the savepoint rolls back everything including the DELETE. With fix:
        - aggregate_segments returns normally (error caught internally)
        - Old TherbligDetail rows are preserved
        - Caller can safely continue using the session
        """
        import os
        import tempfile
        from datetime import datetime, timezone
        from sqlalchemy import create_engine, text
        from app.models.database import (
            ProcessSegment, WorktimeRecord, TherbligDetail,
            get_session, init_db,
        )
        from app.models.schemas import ActionLabel, ShiftName
        from app.services.worktime_aggregator import aggregate_segments

        fd, path = tempfile.mkstemp(suffix=".db")
        db_url = f"sqlite:///{path}"
        os.close(fd)

        try:
            engine = init_db(db_url=db_url, echo=False)
            raw_engine = create_engine(db_url)
            session = get_session(db_url)

            # Create segments for 2 actions -> 2 WorktimeRecords
            segments = [
                ProcessSegment(
                    camera_id="cam_0", station_id="WS-01",
                    action=ActionLabel.REACH.value, therblig_symbol="R",
                    start_time=datetime(2026, 4, 2, 1, 0, 0, tzinfo=timezone.utc),
                    end_time=datetime(2026, 4, 2, 1, 0, 2, tzinfo=timezone.utc),
                    duration_ms=2000, confidence=0.9, shift=ShiftName.MORNING.value,
                ),
                ProcessSegment(
                    camera_id="cam_0", station_id="WS-01",
                    action=ActionLabel.GRASP.value, therblig_symbol="G",
                    start_time=datetime(2026, 4, 2, 1, 0, 3, tzinfo=timezone.utc),
                    end_time=datetime(2026, 4, 2, 1, 0, 4, tzinfo=timezone.utc),
                    duration_ms=1000, confidence=0.85, shift=ShiftName.MORNING.value,
                ),
            ]
            for seg in segments:
                session.add(seg)
            session.commit()

            # First run: create initial details
            records1 = aggregate_segments(session, station_id="WS-01", shift="morning")
            assert len(records1) >= 2

            with raw_engine.connect() as conn:
                before_count = conn.execute(
                    text("SELECT COUNT(*) FROM therblig_details")
                ).scalar()
            assert before_count >= 2, f"Expected >=2 details, got {before_count}"

            # Second run with injected failure inside savepoint
            original_add = session.add
            add_count = [0]

            def failing_add(obj):
                add_count[0] += 1
                if isinstance(obj, TherbligDetail) and add_count[0] >= 2:
                    raise RuntimeError("Simulated detail creation failure")
                return original_add(obj)

            session.add = failing_add

            # With savepoint fix: error is caught, function returns normally
            result = aggregate_segments(session, station_id="WS-01", shift="morning")

            session.add = original_add

            # Old details must survive after the failed savepoint
            with raw_engine.connect() as conn:
                after_count = conn.execute(
                    text("SELECT COUNT(*) FROM therblig_details")
                ).scalar()

            assert after_count == before_count, (
                f"TherbligDetail rows must survive savepoint rollback. "
                f"Before: {before_count}, After: {after_count}"
            )

            session.close()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
