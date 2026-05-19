"""
Tests for PoseFrameSchema hand data extension (T8-04).
"""

import pytest
from typing import Optional


class TestPoseFrameSchemaHandData:
    """T8-04: PoseFrameSchema supports optional hand_landmarks and hand_features."""

    def test_pose_frame_without_hand_data(self):
        """PoseFrameSchema works without hand data (backward compatible)."""
        from app.models.schemas import PoseFrameSchema, LandmarkSchema

        frame = PoseFrameSchema(
            camera_id="cam_01",
            timestamp=1000.0,
            frame_id="frame_001",
            landmarks=[
                LandmarkSchema(name="nose", x=0.5, y=0.5),
            ],
            pose_score=0.95,
        )
        assert frame.hand_landmarks is None
        assert frame.hand_features is None

    def test_pose_frame_with_hand_data(self):
        """PoseFrameSchema accepts hand_landmarks and hand_features."""
        from app.models.schemas import PoseFrameSchema, LandmarkSchema

        frame = PoseFrameSchema(
            camera_id="cam_01",
            timestamp=1000.0,
            frame_id="frame_002",
            landmarks=[
                LandmarkSchema(name="nose", x=0.5, y=0.5),
            ],
            pose_score=0.95,
            hand_landmarks=[
                LandmarkSchema(name="WRIST", x=0.3, y=0.6, z=0.0, visibility=1.0),
            ],
            hand_features={"grip_strength": 0.8, "finger_spread": 0.3},
        )
        assert len(frame.hand_landmarks) == 1
        assert frame.hand_landmarks[0].name == "WRIST"
        assert frame.hand_features["grip_strength"] == pytest.approx(0.8)

    def test_pose_frame_hand_features_mutable(self):
        """hand_features can be updated after construction."""
        from app.models.schemas import PoseFrameSchema

        frame = PoseFrameSchema(
            camera_id="cam_01",
            timestamp=1000.0,
        )
        frame.hand_features = {"grip_strength": 0.5}
        assert frame.hand_features["grip_strength"] == pytest.approx(0.5)
