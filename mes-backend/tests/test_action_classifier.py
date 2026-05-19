"""Tests for the rule-based action classifier."""

import math

import numpy as np
import pytest

from app.models.schemas import ActionLabel
from app.services.action_classifier import (
    FrameFeatures,
    Lmk,
    WindowStats,
    classify_action,
    compute_angle,
    compute_window_stats,
    extract_features,
)


# ── Helpers ─────────────────────────────────────────────────────────────

def make_landmark(
    x: float, y: float, z: float = 0.0, visibility: float = 1.0, name: str = ""
) -> dict:
    return {"name": name, "x": x, "y": y, "z": z, "visibility": visibility}


def make_full_landmarks(
    *,
    nose=(0.5, 0.2),
    left_shoulder=(0.35, 0.35),
    right_shoulder=(0.65, 0.35),
    left_elbow=(0.25, 0.50),
    right_elbow=(0.75, 0.50),
    left_wrist=(0.20, 0.65),
    right_wrist=(0.80, 0.65),
    left_hip=(0.40, 0.60),
    right_hip=(0.60, 0.60),
    left_knee=(0.40, 0.80),
    right_knee=(0.60, 0.80),
    left_ankle=(0.40, 0.95),
    right_ankle=(0.60, 0.95),
    visibility=1.0,
) -> list:
    """Generate a full 33-landmark list with all required joints."""
    lms = [make_landmark(0, 0, 0, 0.1)] * 33  # fill with low-vis

    positions = {
        Lmk.NOSE: nose,
        Lmk.LEFT_SHOULDER: left_shoulder,
        Lmk.RIGHT_SHOULDER: right_shoulder,
        Lmk.LEFT_ELBOW: left_elbow,
        Lmk.RIGHT_ELBOW: right_elbow,
        Lmk.LEFT_WRIST: left_wrist,
        Lmk.RIGHT_WRIST: right_wrist,
        Lmk.LEFT_HIP: left_hip,
        Lmk.RIGHT_HIP: right_hip,
        Lmk.LEFT_KNEE: left_knee,
        Lmk.RIGHT_KNEE: right_knee,
        Lmk.LEFT_ANKLE: left_ankle,
        Lmk.RIGHT_ANKLE: right_ankle,
        Lmk.LEFT_INDEX: left_wrist,
        Lmk.RIGHT_INDEX: right_wrist,
    }
    for idx, (x, y) in positions.items():
        lms[idx] = make_landmark(x, y, 0.0, visibility, f"lm_{idx}")

    return lms


# ── compute_angle tests ─────────────────────────────────────────────────

class TestComputeAngle:
    def test_right_angle(self):
        a = np.array([0.0, 0.0])
        b = np.array([1.0, 0.0])
        c = np.array([1.0, 1.0])
        angle = compute_angle(a, b, c)
        assert abs(angle - 90.0) < 0.1

    def test_straight_line(self):
        a = np.array([0.0, 0.0])
        b = np.array([1.0, 0.0])
        c = np.array([2.0, 0.0])
        angle = compute_angle(a, b, c)
        assert abs(angle - 180.0) < 0.1

    def test_zero_length(self):
        a = np.array([0.0, 0.0])
        b = np.array([0.0, 0.0])
        c = np.array([1.0, 0.0])
        angle = compute_angle(a, b, c)
        assert math.isfinite(angle)


# ── extract_features tests ──────────────────────────────────────────────

class TestExtractFeatures:
    def test_valid_landmarks(self):
        lms = make_full_landmarks()
        feat = extract_features(lms)
        assert feat is not None
        assert feat.visible_fraction > 0.3  # 15 of 33 landmarks have vis=1.0
        assert bool(feat.is_standing) is True

    def test_insufficient_landmarks(self):
        feat = extract_features([])
        assert feat is None

    def test_low_visibility_returns_none(self):
        lms = make_full_landmarks(visibility=0.1)
        feat = extract_features(lms)
        assert feat is None

    def test_wrist_heights(self):
        # Wrists below shoulders -> avg_wrist_y > avg_shoulder_y
        lms = make_full_landmarks(
            left_wrist=(0.20, 0.75),
            right_wrist=(0.80, 0.75),
        )
        feat = extract_features(lms)
        assert feat is not None
        assert feat.avg_wrist_y > feat.avg_shoulder_y

    def test_wrist_spread(self):
        lms = make_full_landmarks(
            left_wrist=(0.10, 0.65),
            right_wrist=(0.90, 0.65),
        )
        feat = extract_features(lms)
        assert feat is not None
        assert feat.wrist_spread > 0.5

    def test_sitting_posture(self):
        lms = make_full_landmarks(
            left_knee=(0.35, 0.65),
            right_knee=(0.65, 0.65),
            left_ankle=(0.38, 0.68),
            right_ankle=(0.62, 0.68),
        )
        feat = extract_features(lms)
        assert feat is not None
        assert bool(feat.is_standing) is False


# ── compute_window_stats tests ─────────────────────────────────────────

class TestComputeWindowStats:
    def test_empty_list(self):
        stats = compute_window_stats([])
        assert stats.n_frames == 0

    def test_single_frame(self):
        lms = make_full_landmarks()
        feat = extract_features(lms)
        stats = compute_window_stats([feat])
        assert stats.n_frames == 1
        assert stats.avg_visible_fraction > 0

    def test_multiple_frames(self):
        features = []
        for i in range(30):
            # Simulate wrist going up and down
            offset = 0.05 * math.sin(i * 0.3)
            lms = make_full_landmarks(
                left_wrist=(0.20, 0.65 + offset),
                right_wrist=(0.80, 0.65 - offset),
            )
            feat = extract_features(lms)
            if feat:
                features.append(feat)

        stats = compute_window_stats(features)
        assert stats.n_frames == 30
        assert stats.std_wrist_y > 0  # motion detected


# ── classify_action tests ───────────────────────────────────────────────

class TestClassifyAction:
    def test_idle_low_visibility(self):
        stats = WindowStats(avg_visible_fraction=0.1, n_frames=30)
        action, conf, region = classify_action(stats)
        assert action == ActionLabel.IDLE
        assert conf >= 0.8

    def test_wait_still_arms_down(self):
        stats = WindowStats(
            avg_left_elbow=160.0,
            avg_right_elbow=160.0,
            avg_left_shoulder=20.0,
            avg_right_shoulder=20.0,
            std_wrist_y=0.01,
            std_wrist_spread=0.01,
            avg_wrist_y=0.7,
            avg_shoulder_y=0.35,
            avg_visible_fraction=0.9,
            n_frames=30,
        )
        action, conf, region = classify_action(stats)
        assert action == ActionLabel.WAIT

    def test_inspect_hands_high_still(self):
        stats = WindowStats(
            avg_left_elbow=90.0,
            avg_right_elbow=90.0,
            avg_left_shoulder=45.0,
            avg_right_shoulder=45.0,
            std_wrist_y=0.02,
            std_wrist_spread=0.02,
            avg_wrist_y=0.2,
            avg_shoulder_y=0.35,
            avg_visible_fraction=0.9,
            n_frames=30,
        )
        action, conf, region = classify_action(stats)
        assert action == ActionLabel.INSPECT

    def test_reach_shoulder_elevated(self):
        stats = WindowStats(
            avg_left_elbow=130.0,
            avg_right_elbow=130.0,
            avg_left_shoulder=80.0,
            avg_right_shoulder=80.0,
            std_wrist_y=0.07,
            std_wrist_spread=0.02,
            avg_wrist_y=0.3,
            avg_shoulder_y=0.35,
            avg_visible_fraction=0.9,
            n_frames=30,
        )
        action, conf, region = classify_action(stats)
        assert action == ActionLabel.REACH

    def test_assemble_hands_close(self):
        stats = WindowStats(
            avg_left_elbow=100.0,
            avg_right_elbow=100.0,
            avg_left_shoulder=50.0,
            avg_right_shoulder=50.0,
            std_wrist_y=0.03,
            avg_wrist_spread=0.05,
            avg_wrist_y=0.5,
            avg_shoulder_y=0.35,
            avg_visible_fraction=0.9,
            n_frames=30,
        )
        action, conf, region = classify_action(stats)
        assert action == ActionLabel.ASSEMBLE

    def test_always_returns_tuple(self):
        stats = WindowStats(n_frames=30)
        result = classify_action(stats)
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert isinstance(result[0], ActionLabel)
        assert 0.0 <= result[1] <= 1.0
