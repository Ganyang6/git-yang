"""
Tests for PoseFrameConsumer hand data adaptation (T8-05).
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_msg(fields: dict) -> dict:
    """Helper to create a mock Redis Stream message."""
    return {
        "stream": "mes:pose_frames",
        "msg_id": "1-0",
        "fields": fields,
    }


def _make_pose_landmarks() -> list[dict]:
    """Return minimal valid pose landmarks (33 points)."""
    landmarks = []
    for i in range(33):
        landmarks.append({
            "name": f"point_{i}",
            "x": 0.5,
            "y": 0.5,
            "z": 0.0,
            "visibility": 0.9,
        })
    return landmarks


class TestPoseFrameConsumerHandData:
    """T8-05: PoseFrameConsumer parses hand data from Redis Stream."""

    @pytest.fixture
    def consumer(self):
        """Create a PoseFrameConsumer with a mock Redis client."""
        mock_redis = MagicMock()
        mock_redis.consume_stream = AsyncMock(return_value=[])
        mock_redis.ack_message = AsyncMock(return_value=True)

        from app.services.stream_consumers import PoseFrameConsumer
        c = PoseFrameConsumer(redis_client=mock_redis)
        return c

    @pytest.mark.asyncio
    async def test_process_message_with_hand_data(self, consumer):
        """Message with hand_landmarks/hand_features should pass them to pipeline."""
        fields = {
            "camera_id": "cam_01",
            "timestamp": "1000.0",
            "frame_id": "frame_001",
            "landmarks": json.dumps(_make_pose_landmarks()),
            "pose_score": "0.95",
            "station_id": "WS-01",
            "hand_landmarks": json.dumps([
                {"name": "WRIST", "x": 0.3, "y": 0.6, "z": 0.0, "visibility": 1.0},
            ]),
            "hand_features": json.dumps({
                "grip_strength": 0.8,
                "finger_spread": 0.3,
                "pinch_distance": 0.05,
            }),
        }
        msg = _make_msg(fields)

        # Mock the pipeline to capture what was passed
        captured = {}
        mock_pipeline = MagicMock()
        mock_pipeline.process_frame = MagicMock(side_effect=lambda frame, **kw: (
            captured.update({"frame": frame, "kwargs": kw}),
            None,
        )[1])
        consumer._pipeline = mock_pipeline

        await consumer._process_message(msg)

        # Verify hand data was passed to pipeline
        assert captured["kwargs"].get("hand_features") is not None
        assert captured["kwargs"]["hand_features"]["grip_strength"] == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_process_message_without_hand_data(self, consumer):
        """Message without hand data should work (backward compatible)."""
        fields = {
            "camera_id": "cam_01",
            "timestamp": "1000.0",
            "frame_id": "frame_002",
            "landmarks": json.dumps(_make_pose_landmarks()),
            "pose_score": "0.95",
            "station_id": "WS-01",
        }
        msg = _make_msg(fields)

        captured = {}
        mock_pipeline = MagicMock()
        mock_pipeline.process_frame = MagicMock(side_effect=lambda frame, **kw: (
            captured.update({"frame": frame, "kwargs": kw}),
            None,
        )[1])
        consumer._pipeline = mock_pipeline

        await consumer._process_message(msg)

        # Should not crash; hand_features may be None or empty dict
        hf = captured["kwargs"].get("hand_features")
        # Both None and {} are acceptable for "no hand data"
        assert hf is None or hf == {}
