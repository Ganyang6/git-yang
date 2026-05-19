"""Tests for video progress publishing (T9-03)."""

import json
from unittest.mock import MagicMock, patch

import pytest


class TestPublishVideoProgress:
    """T9-03: _publish_video_progress function tests."""

    def test_publishes_json_message_to_redis(self):
        """_publish_video_progress sends correct JSON to Redis Pub/Sub."""
        from main import _publish_video_progress

        captured = {}

        def capture_publish(channel, message):
            captured["channel"] = channel
            captured["message"] = message

        mock_adapter = MagicMock()
        mock_adapter._redis_client.publish.side_effect = capture_publish

        with patch("main._safe_redis_call", side_effect=lambda fn, **kw: fn()):
            _publish_video_progress(
                mock_adapter, "task-123", 0.5,
                processed_frames=250, total_frames=500,
                status="processing",
            )

        assert "message" in captured

    def test_message_format_matches_spec(self):
        """Published message contains all required fields per T9-03 spec."""
        from main import _publish_video_progress

        captured_msg = None

        def capture_publish(channel, message):
            nonlocal captured_msg
            captured_msg = message

        mock_adapter = MagicMock()
        mock_adapter._redis_client.publish.side_effect = capture_publish

        # Mock _safe_redis_call to execute the lambda directly
        with patch("main._safe_redis_call", side_effect=lambda fn, **kw: fn()):
            _publish_video_progress(
                mock_adapter, "task-abc", 0.3,
                processed_frames=150, total_frames=500,
                status="processing",
            )

        assert captured_msg is not None
        data = json.loads(captured_msg)
        assert data["task_id"] == "task-abc"
        assert data["progress"] == 0.3
        assert data["processed_frames"] == 150
        assert data["total_frames"] == 500
        assert data["status"] == "processing"
        assert "duration_s" in data
        assert "error" in data

    def test_completed_status_includes_duration(self):
        """Completed progress message includes duration_s."""
        from main import _publish_video_progress

        captured_msg = None

        def capture_publish(channel, message):
            nonlocal captured_msg
            captured_msg = message

        mock_adapter = MagicMock()
        mock_adapter._redis_client.publish.side_effect = capture_publish

        with patch("main._safe_redis_call", side_effect=lambda fn, **kw: fn()):
            _publish_video_progress(
                mock_adapter, "task-done", 1.0,
                processed_frames=500, total_frames=500,
                status="completed", duration_s=45.2,
            )

        data = json.loads(captured_msg)
        assert data["status"] == "completed"
        assert data["progress"] == 1.0
        assert data["duration_s"] == 45.2

    def test_failed_status_includes_error(self):
        """Failed progress message includes error string."""
        from main import _publish_video_progress

        captured_msg = None

        def capture_publish(channel, message):
            nonlocal captured_msg
            captured_msg = message

        mock_adapter = MagicMock()
        mock_adapter._redis_client.publish.side_effect = capture_publish

        with patch("main._safe_redis_call", side_effect=lambda fn, **kw: fn()):
            _publish_video_progress(
                mock_adapter, "task-fail", 0.15,
                processed_frames=75, total_frames=500,
                status="failed", error="Redis connection lost",
            )

        data = json.loads(captured_msg)
        assert data["status"] == "failed"
        assert data["error"] == "Redis connection lost"

    def test_publish_uses_correct_channel_name(self):
        """Publishes to channel:video_progress:{task_id}."""
        from main import _publish_video_progress

        captured_channel = None

        def capture_publish(channel, message):
            nonlocal captured_channel
            captured_channel = channel

        mock_adapter = MagicMock()
        mock_adapter._redis_client.publish.side_effect = capture_publish

        with patch("main._safe_redis_call", side_effect=lambda fn, **kw: fn()):
            _publish_video_progress(
                mock_adapter, "my-uuid-123", 0.5,
                processed_frames=100, total_frames=200,
            )

        assert captured_channel == "channel:video_progress:my-uuid-123"

    def test_publish_failure_does_not_raise(self):
        """Redis publish failure is caught and logged, not raised."""
        from main import _publish_video_progress

        mock_adapter = MagicMock()
        mock_adapter._redis_client.publish.side_effect = ConnectionError("Redis down")

        # Should not raise despite Redis error
        _publish_video_progress(
            mock_adapter, "task-err", 0.1,
            processed_frames=10, total_frames=100,
        )


class TestTaskHashUpdate:
    """Tests for _update_task_hash function."""

    def test_completed_updates_redis_hash(self):
        """Completed status updates mes:video:tasks hash with terminal fields."""
        from main import _update_task_hash, _REDIS_KEY_TASKS

        # Build a realistic existing task dict
        existing_task = {
            "task_id": "task-complete-001",
            "filename": "video.mp4",
            "status": "processing",
            "created_at": 1000.0,
            "started_at": 1001.0,
            "completed_at": None,
            "progress": 0.5,
            "total_frames": 0,
        }

        # Mock the underlying sync redis client
        mock_redis = MagicMock()
        mock_redis.hget.return_value = json.dumps(existing_task)

        # Adapter structure: adapter._client.client -> raw redis.Redis
        mock_adapter = MagicMock()
        mock_adapter._client.client = mock_redis

        _update_task_hash(
            mock_adapter, "task-complete-001", "completed",
            total_frames=500, duration_s=45.2,
            error="", progress=1.0,
        )

        # Verify hget was called with correct key
        mock_redis.hget.assert_called_once_with(_REDIS_KEY_TASKS, "task-complete-001")

        # Verify hset was called
        mock_redis.hset.assert_called_once()
        args, _ = mock_redis.hset.call_args
        assert args[0] == _REDIS_KEY_TASKS
        assert args[1] == "task-complete-001"

        # Verify the updated task has correct terminal fields
        updated = json.loads(args[2])
        assert updated["status"] == "completed"
        assert updated["total_frames"] == 500
        assert updated["duration_s"] == 45.2
        assert updated["progress"] == 1.0
        assert updated["completed_at"] is not None
        assert "error" not in updated or updated["error"] == ""

    def test_failed_updates_redis_hash_with_error(self):
        """Failed status writes error to mes:video:tasks hash."""
        from main import _update_task_hash

        existing_task = {
            "task_id": "task-fail-002",
            "filename": "bad_video.mp4",
            "status": "processing",
            "created_at": 1000.0,
            "started_at": 1001.0,
        }

        mock_redis = MagicMock()
        mock_redis.hget.return_value = json.dumps(existing_task)

        mock_adapter = MagicMock()
        mock_adapter._client.client = mock_redis

        _update_task_hash(
            mock_adapter, "task-fail-002", "failed",
            total_frames=100, duration_s=10.0,
            error="Processing error: frame read timeout", progress=0.15,
        )

        mock_redis.hset.assert_called_once()
        args, _ = mock_redis.hset.call_args
        updated = json.loads(args[2])
        assert updated["status"] == "failed"
        assert updated["error"] == "Processing error: frame read timeout"
        assert updated["progress"] == 0.15

    def test_skips_if_no_client(self):
        """_update_task_hash skips when adapter._client is None."""
        from main import _update_task_hash

        mock_adapter = MagicMock()
        mock_adapter._client = None

        # Should not raise
        _update_task_hash(
            mock_adapter, "task-no-client", "completed",
            total_frames=100, duration_s=5.0,
            error="", progress=1.0,
        )

    def test_skips_if_no_raw_client(self):
        """_update_task_hash skips when RedisSyncClient.client is None."""
        from main import _update_task_hash

        mock_adapter = MagicMock()
        mock_adapter._client.client = None

        # Should not raise
        _update_task_hash(
            mock_adapter, "task-no-raw", "completed",
            total_frames=100, duration_s=5.0,
            error="", progress=1.0,
        )

    def test_skips_if_task_not_in_hash(self):
        """_update_task_hash skips when hget returns None."""
        from main import _update_task_hash

        mock_redis = MagicMock()
        mock_redis.hget.return_value = None

        mock_adapter = MagicMock()
        mock_adapter._client.client = mock_redis

        # Should not raise
        _update_task_hash(
            mock_adapter, "nonexistent", "completed",
            total_frames=100, duration_s=5.0,
            error="", progress=1.0,
        )

        # hset should NOT be called
        mock_redis.hset.assert_not_called()


class TestVideoPipelineArgparse:
    """T9-03: --task-id CLI argument tests."""

    def test_task_id_argument_exists(self):
        """main.py argparse includes --task-id argument."""
        from main import _build_arg_parser

        parser = _build_arg_parser()
        actions = [a.dest for a in parser._actions]
        assert "task_id" in actions

    def test_task_id_default_empty(self):
        """--task-id defaults to empty string."""
        from main import _build_arg_parser

        parser = _build_arg_parser()
        args = parser.parse_args([])
        assert args.task_id == ""

    def test_task_id_from_cli(self):
        """--task-id value is parsed from CLI."""
        from main import _build_arg_parser

        parser = _build_arg_parser()
        args = parser.parse_args(["--task-id", "abc-123"])
        assert args.task_id == "abc-123"

    def test_task_id_from_env(self):
        """TASK_ID env variable is used as fallback."""
        import os
        from main import _build_arg_parser

        old = os.environ.pop("TASK_ID", None)
        os.environ["TASK_ID"] = "env-uuid-999"

        try:
            parser = _build_arg_parser()
            args = parser.parse_args([])
            assert args.task_id == "env-uuid-999"
        finally:
            os.environ.pop("TASK_ID", None)
            if old is not None:
                os.environ["TASK_ID"] = old
