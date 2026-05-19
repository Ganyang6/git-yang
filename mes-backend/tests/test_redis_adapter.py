"""
Redis adapter unit tests.
Covers: publish_pose_frame with/without hand data.
"""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestPublishPoseFrame:
    """publish_pose_frame message format."""

    @pytest.fixture(autouse=True)
    def _setup_adapter(self):
        """Create a PerceptionAdapter with a mock Redis client."""
        self.mock_xadd_calls = []
        mock_sync_client = MagicMock()
        mock_sync_client.ping.return_value = True

        def mock_xadd(stream_key, fields, maxlen=None, approximate=None):
            self.mock_xadd_calls.append({"stream": stream_key, "fields": fields})
            return b"1-0"

        mock_sync_client.client.xadd.side_effect = mock_xadd

        with patch("app.perception.redis_adapter.RedisSyncClient", return_value=mock_sync_client):
            from app.perception.redis_adapter import PerceptionAdapter
            self.adapter = PerceptionAdapter(redis_url="redis://localhost:6379/0")
            self.adapter.connect()

    def _get_last_xadd_fields(self):
        """Return fields dict from the last XADD call."""
        return self.mock_xadd_calls[-1]["fields"]

    def test_publish_pose_frame_without_hand_data(self):
        """Without hand_landmarks/hand_features, fields contain empty defaults."""
        self.adapter.publish_pose_frame(
            camera_id="cam_01",
            timestamp=1000.0,
            frame_id="00000000000000000001",
            landmarks=[{"name": "nose", "x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.9}],
            pose_score=0.95,
            station_id="WS-01",
            landmark_count=33,
        )
        fields = self._get_last_xadd_fields()
        assert "hand_landmarks" in fields
        assert json.loads(fields["hand_landmarks"]) == []
        assert "hand_features" in fields
        assert json.loads(fields["hand_features"]) == {}

    def test_publish_pose_frame_with_hand_data(self):
        """With hand_landmarks/hand_features, fields contain serialized JSON."""
        hand_landmarks = [
            {"name": "WRIST", "x": 0.3, "y": 0.6, "z": 0.0, "visibility": 1.0},
            {"name": "INDEX_FINGER_TIP", "x": 0.35, "y": 0.45, "z": 0.0, "visibility": 1.0},
        ]
        hand_features = {"grip_strength": 0.8, "finger_spread": 0.3, "pinch_distance": 0.05}

        self.adapter.publish_pose_frame(
            camera_id="cam_01",
            timestamp=1000.0,
            frame_id="00000000000000000002",
            landmarks=[{"name": "nose", "x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.9}],
            pose_score=0.95,
            station_id="WS-01",
            landmark_count=33,
            hand_landmarks=hand_landmarks,
            hand_features=hand_features,
        )
        fields = self._get_last_xadd_fields()
        parsed_hand = json.loads(fields["hand_landmarks"])
        assert len(parsed_hand) == 2
        assert parsed_hand[0]["name"] == "WRIST"

        parsed_features = json.loads(fields["hand_features"])
        assert parsed_features["grip_strength"] == 0.8
        assert parsed_features["finger_spread"] == 0.3
        assert parsed_features["pinch_distance"] == 0.05

    def test_hand_count_reflected_in_fields(self):
        """hand_count field should be present and correct."""
        self.adapter.publish_pose_frame(
            camera_id="cam_01",
            timestamp=1000.0,
            frame_id="00000000000000000003",
            landmarks=[],
            pose_score=0.9,
            hand_count=2,
        )
        fields = self._get_last_xadd_fields()
        assert fields["hand_count"] == "2"
