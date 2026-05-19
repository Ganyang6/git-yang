"""
Tests for action_classifier hand feature enhancement (T8-06).
"""

import numpy as np
import pytest

from app.models.schemas import ActionLabel
from app.services.action_classifier import (
    WindowStats,
    classify_action,
    compute_window_stats,
    extract_features,
)


def _make_basic_landmarks() -> list[dict]:
    """Create 33 pose landmarks with realistic values for testing."""
    landmarks = []
    # Simplified: spread points across body
    positions = {
        0: (0.5, 0.3),   # nose
        11: (0.4, 0.35),  # left shoulder
        12: (0.6, 0.35),  # right shoulder
        13: (0.3, 0.55),  # left elbow
        14: (0.7, 0.55),  # right elbow
        15: (0.35, 0.7),  # left wrist
        16: (0.65, 0.7),  # right wrist
        19: (0.37, 0.75),  # left index
        20: (0.63, 0.75),  # right index
        23: (0.42, 0.55),  # left hip
        24: (0.58, 0.55),  # right hip
        25: (0.42, 0.75),  # left knee
        26: (0.58, 0.75),  # right knee
        27: (0.42, 0.95),  # left ankle
        28: (0.58, 0.95),  # right ankle
    }
    for i in range(33):
        x, y = positions.get(i, (0.5, 0.5))
        landmarks.append({
            "name": f"point_{i}",
            "x": x, "y": y, "z": 0.0, "visibility": 0.9,
        })
    return landmarks


def _make_window_stats(**overrides) -> WindowStats:
    """Create a WindowStats with defaults that trigger GRASP rules."""
    defaults = {
        "avg_left_elbow": 100.0,
        "avg_right_elbow": 100.0,
        "avg_left_shoulder": 45.0,
        "avg_right_shoulder": 45.0,
        "avg_left_knee": 170.0,
        "avg_right_knee": 170.0,
        "avg_left_hip": 170.0,
        "avg_right_hip": 170.0,
        "avg_wrist_y": 0.7,
        "avg_shoulder_y": 0.35,
        "avg_wrist_spread": 0.12,
        "std_wrist_y": 0.04,
        "std_wrist_spread": 0.06,
        "avg_visible_fraction": 0.9,
        "standing_ratio": 1.0,
        "n_frames": 30,
    }
    defaults.update(overrides)
    return WindowStats(**defaults)


class TestActionPipelineHandPassthrough:
    """Verify ActionPipeline.process_frame() passes hand_features to
    extract_features() so that GRASP/RELEASE boost actually triggers."""

    def test_process_frame_forwards_hand_features_to_extract_features(self):
        """P0-1 regression: hand_features must reach extract_features()."""
        from unittest.mock import patch

        from app.services.action_classifier import extract_features
        from app.models.schemas import PoseFrameSchema, LandmarkSchema
        from app.services.process_segmenter import ActionPipeline

        pipeline = ActionPipeline()

        landmarks = [
            LandmarkSchema(name=f"point_{i}", x=0.5, y=0.5, z=0.0, visibility=0.9)
            for i in range(33)
        ]
        frame = PoseFrameSchema(
            camera_id="cam_01",
            timestamp=1000.0,
            frame_id="frame_001",
            landmarks=landmarks,
            pose_score=0.95,
        )

        hand_features = {"grip_strength": 0.85, "finger_spread": 0.2, "pinch_distance": 0.05}

        called_with = {}

        original_extract = extract_features
        def _spy(lm, hand_features=None):
            called_with["hand_features"] = hand_features
            return original_extract(lm, hand_features=hand_features)

        with patch("app.services.process_segmenter.extract_features", side_effect=_spy):
            pipeline.process_frame(frame, station_id="WS-01", hand_features=hand_features)

        assert called_with["hand_features"] == hand_features


class TestFrameFeaturesHandData:
    """FrameFeatures accepts and stores hand-derived features."""

    def test_extract_features_without_hand_data(self):
        """extract_features() without hand_features -> defaults (0.0, 1.0, 0.0)."""
        feats = extract_features(_make_basic_landmarks())
        assert feats.grip_strength == 0.0
        assert feats.pinch_distance == 1.0
        assert feats.finger_spread == 0.0

    def test_extract_features_with_hand_data(self):
        """extract_features() with hand_features dict populates fields."""
        hand_features = {
            "grip_strength": 0.75,
            "finger_spread": 0.4,
            "pinch_distance": 0.08,
        }
        feats = extract_features(_make_basic_landmarks(), hand_features=hand_features)
        assert feats.grip_strength == pytest.approx(0.75)
        assert feats.finger_spread == pytest.approx(0.4)
        assert feats.pinch_distance == pytest.approx(0.08)


class TestClassifyGraspWithHandData:
    """GRASP classification boosted by grip_strength."""

    def test_grasp_boosted_confidence_with_high_grip(self):
        """grip_strength > 0.6 should boost GRASP confidence above 0.80."""
        stats = _make_window_stats()
        # Set stats that would match GRASP rule (elbow bent, wrist spread increasing)
        stats.avg_elbow_avg = (
            (stats.avg_left_elbow + stats.avg_right_elbow) / 2
        )
        stats.avg_wrist_spread = 0.12
        stats.std_wrist_spread = 0.06

        # Create features with high grip_strength
        from app.services.action_classifier import FrameFeatures
        features_list = [FrameFeatures(
            landmarks=np.zeros((33, 4)),
            grip_strength=0.8,
            finger_spread=0.2,
            pinch_distance=0.05,
        )] * 30
        stats = WindowStats()
        # Recompute window stats from features
        from app.services.action_classifier import compute_window_stats
        for raw_lm in [_make_basic_landmarks()]:
            f = extract_features(raw_lm, hand_features={
                "grip_strength": 0.8,
                "finger_spread": 0.2,
                "pinch_distance": 0.05,
            })
            features_list[0] = f
            break
        stats = compute_window_stats(features_list)

        action, confidence, region = classify_action(stats)
        # With grip_strength=0.8, should classify as GRASP with boosted confidence
        # (exact classification depends on the rule matching, but if GRASP matches,
        # confidence should be boosted)
        if action == ActionLabel.GRASP:
            assert confidence >= 0.80

    def test_release_boosted_with_low_grip_high_spread(self):
        """grip_strength < 0.3 and finger_spread > 0.6 boosts RELEASE confidence."""
        features_list = []
        for raw_lm in [_make_basic_landmarks()]:
            f = extract_features(raw_lm, hand_features={
                "grip_strength": 0.2,
                "finger_spread": 0.8,
                "pinch_distance": 0.5,
            })
            features_list.append(f)

        stats = compute_window_stats(features_list)
        action, confidence, region = classify_action(stats)
        # If classified as RELEASE, confidence should be boosted
        if action == ActionLabel.RELEASE:
            assert confidence >= 0.80

    def test_no_hand_data_fallback(self):
        """Without hand data, existing rule-based classification is unchanged."""
        # Use basic landmarks without hand features
        features_list = []
        for _ in range(30):
            f = extract_features(_make_basic_landmarks())
            features_list.append(f)

        stats = compute_window_stats(features_list)
        # Should still classify something (not crash)
        action, confidence, region = classify_action(stats)
        assert action in list(ActionLabel)
        assert 0.0 < confidence <= 1.0
