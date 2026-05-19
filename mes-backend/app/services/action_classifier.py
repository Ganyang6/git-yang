"""
Rule-based action classifier.

Consumes a sliding window of pose landmarks and classifies the worker's
current action using joint-angle heuristics and body-region motion
patterns.  No ML model is required for the initial deployment; the rule
engine provides deterministic, interpretable results that can later be
augmented or replaced by an ONNX classifier.

Classification logic:
  - Compute joint angles (elbow, shoulder, knee, hip) from landmark triples.
  - Compute joint velocities (angular velocity between consecutive frames).
  - Apply hierarchical rules: upper-body-dominant vs full-body-dominant.
  - Return action label + confidence + dominant body region.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.models.schemas import ActionLabel

logger = logging.getLogger(__name__)


# ── Pose landmark indices (MediaPipe 33-point) ───────────────────────────

class Lmk:
    """Shorthand for landmark indices used in classification rules."""
    NOSE = 0
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_ELBOW = 13
    RIGHT_ELBOW = 14
    LEFT_WRIST = 15
    RIGHT_WRIST = 16
    LEFT_HIP = 23
    RIGHT_HIP = 24
    LEFT_KNEE = 25
    RIGHT_KNEE = 26
    LEFT_ANKLE = 27
    RIGHT_ANKLE = 28
    LEFT_INDEX = 19
    RIGHT_INDEX = 20


@dataclass
class FrameFeatures:
    """
    Pre-computed features for a single frame.

    These features are extracted by the sliding window and fed to the
    classification rules.
    """
    # Raw landmark array (33, 4) - x, y, z, visibility
    landmarks: np.ndarray

    # Joint angles in degrees
    left_elbow_angle: float = 0.0
    right_elbow_angle: float = 0.0
    left_shoulder_angle: float = 0.0
    right_shoulder_angle: float = 0.0
    left_knee_angle: float = 0.0
    right_knee_angle: float = 0.0
    left_hip_angle: float = 0.0
    right_hip_angle: float = 0.0

    # Key point heights (y-axis, 0=top, 1=bottom in image space)
    avg_wrist_y: float = 0.5
    avg_shoulder_y: float = 0.5
    avg_hip_y: float = 0.5

    # Wrist spread (horizontal distance between left and right wrist)
    wrist_spread: float = 0.0

    # Visibility: fraction of landmarks above threshold
    visible_fraction: float = 0.0

    # Whether the person appears to be standing (hips above knees)
    is_standing: bool = True

    # Hand-derived features (from HandEstimator, optional)
    grip_strength: float = 0.0     # 0=open hand, 1=fully closed fist
    pinch_distance: float = 1.0   # thumb-index tip distance, 0=pinched
    finger_spread: float = 0.0    # 0=closed, 1=fully spread


def compute_angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """
    Compute the angle at point b formed by segments ba and bc, in degrees.

    Each point is expected to be a 2D or 3D numpy array [x, y, (z)].
    """
    ba = a - b
    bc = c - b

    cos_angle = np.dot(ba, bc) / (
        np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8
    )
    cos_angle = np.clip(cos_angle, -1.0, 1.0)
    return float(np.degrees(np.arccos(cos_angle)))


def extract_features(landmarks: List[Dict], hand_features: Dict = None) -> Optional[FrameFeatures]:
    """
    Extract frame features from a list of landmark dicts.

    Args:
        landmarks: List of {name, x, y, z, visibility} dicts.

    Returns:
        FrameFeatures, or None if insufficient visible landmarks.
    """
    if not landmarks or len(landmarks) < 33:
        return None

    arr = np.array([[lm["x"], lm["y"], lm["z"], lm["visibility"]] for lm in landmarks])
    vis = arr[:, 3]

    visible_mask = vis > 0.5
    if visible_mask.sum() < 10:
        return None

    feat = FrameFeatures(landmarks=arr, visible_fraction=float(visible_mask.sum()) / 33)

    def lmk(idx: int) -> np.ndarray:
        return arr[idx, :2]

    # Joint angles
    feat.left_elbow_angle = compute_angle(
        lmk(Lmk.LEFT_SHOULDER), lmk(Lmk.LEFT_ELBOW), lmk(Lmk.LEFT_WRIST)
    )
    feat.right_elbow_angle = compute_angle(
        lmk(Lmk.RIGHT_SHOULDER), lmk(Lmk.RIGHT_ELBOW), lmk(Lmk.RIGHT_WRIST)
    )
    feat.left_shoulder_angle = compute_angle(
        lmk(Lmk.LEFT_HIP), lmk(Lmk.LEFT_SHOULDER), lmk(Lmk.LEFT_ELBOW)
    )
    feat.right_shoulder_angle = compute_angle(
        lmk(Lmk.RIGHT_HIP), lmk(Lmk.RIGHT_SHOULDER), lmk(Lmk.RIGHT_ELBOW)
    )
    feat.left_knee_angle = compute_angle(
        lmk(Lmk.LEFT_HIP), lmk(Lmk.LEFT_KNEE), lmk(Lmk.LEFT_ANKLE)
    )
    feat.right_knee_angle = compute_angle(
        lmk(Lmk.RIGHT_HIP), lmk(Lmk.RIGHT_KNEE), lmk(Lmk.RIGHT_ANKLE)
    )
    feat.left_hip_angle = compute_angle(
        lmk(Lmk.LEFT_SHOULDER), lmk(Lmk.LEFT_HIP), lmk(Lmk.LEFT_KNEE)
    )
    feat.right_hip_angle = compute_angle(
        lmk(Lmk.RIGHT_SHOULDER), lmk(Lmk.RIGHT_HIP), lmk(Lmk.RIGHT_KNEE)
    )

    # Key heights (y: 0=top, 1=bottom)
    feat.avg_wrist_y = (arr[Lmk.LEFT_WRIST, 1] + arr[Lmk.RIGHT_WRIST, 1]) / 2
    feat.avg_shoulder_y = (arr[Lmk.LEFT_SHOULDER, 1] + arr[Lmk.RIGHT_SHOULDER, 1]) / 2
    feat.avg_hip_y = (arr[Lmk.LEFT_HIP, 1] + arr[Lmk.RIGHT_HIP, 1]) / 2

    # Wrist spread
    feat.wrist_spread = abs(arr[Lmk.LEFT_WRIST, 0] - arr[Lmk.RIGHT_WRIST, 0])

    # Standing detection: hips significantly above ankles
    avg_ankle_y = (arr[Lmk.LEFT_ANKLE, 1] + arr[Lmk.RIGHT_ANKLE, 1]) / 2
    feat.is_standing = (avg_ankle_y - feat.avg_hip_y) > 0.15

    # Populate hand-derived features if available
    if hand_features:
        feat.grip_strength = float(hand_features.get("grip_strength", 0.0))
        feat.pinch_distance = float(hand_features.get("pinch_distance", 1.0))
        feat.finger_spread = float(hand_features.get("finger_spread", 0.0))

    return feat


@dataclass
class WindowStats:
    """Aggregate statistics computed over a sliding window of FrameFeatures."""
    avg_left_elbow: float = 0.0
    avg_right_elbow: float = 0.0
    avg_left_shoulder: float = 0.0
    avg_right_shoulder: float = 0.0
    avg_left_knee: float = 0.0
    avg_right_knee: float = 0.0
    avg_left_hip: float = 0.0
    avg_right_hip: float = 0.0
    avg_wrist_y: float = 0.5
    avg_shoulder_y: float = 0.35
    avg_wrist_spread: float = 0.0
    std_wrist_y: float = 0.0
    std_wrist_spread: float = 0.0
    avg_visible_fraction: float = 0.0
    standing_ratio: float = 1.0
    n_frames: int = 0
    # Hand-derived aggregates (averaged over window)
    avg_grip_strength: float = 0.0
    avg_pinch_distance: float = 1.0
    avg_finger_spread: float = 0.0
    has_hand_data: bool = False


def compute_window_stats(features_list: List[FrameFeatures]) -> WindowStats:
    """Aggregate features over the full sliding window."""
    if not features_list:
        return WindowStats()

    n = len(features_list)
    stats = WindowStats(n_frames=n)

    stats.avg_left_elbow = np.mean([f.left_elbow_angle for f in features_list])
    stats.avg_right_elbow = np.mean([f.right_elbow_angle for f in features_list])
    stats.avg_left_shoulder = np.mean([f.left_shoulder_angle for f in features_list])
    stats.avg_right_shoulder = np.mean([f.right_shoulder_angle for f in features_list])
    stats.avg_left_knee = np.mean([f.left_knee_angle for f in features_list])
    stats.avg_right_knee = np.mean([f.right_knee_angle for f in features_list])
    stats.avg_left_hip = np.mean([f.left_hip_angle for f in features_list])
    stats.avg_right_hip = np.mean([f.right_hip_angle for f in features_list])
    stats.avg_wrist_y = np.mean([f.avg_wrist_y for f in features_list])
    stats.avg_shoulder_y = np.mean([f.avg_shoulder_y for f in features_list])
    stats.std_wrist_y = np.std([f.avg_wrist_y for f in features_list])
    stats.avg_wrist_spread = np.mean([f.wrist_spread for f in features_list])
    stats.std_wrist_spread = np.std([f.wrist_spread for f in features_list])
    stats.avg_visible_fraction = np.mean([f.visible_fraction for f in features_list])
    stats.standing_ratio = np.mean([1.0 if f.is_standing else 0.0 for f in features_list])

    # Aggregate hand-derived features
    hand_grips = [f.grip_strength for f in features_list if f.grip_strength > 0 or f.pinch_distance < 1.0 or f.finger_spread > 0.0]
    if hand_grips:
        stats.has_hand_data = True
        stats.avg_grip_strength = np.mean([f.grip_strength for f in features_list])
        stats.avg_pinch_distance = np.mean([f.pinch_distance for f in features_list])
        stats.avg_finger_spread = np.mean([f.finger_spread for f in features_list])

    return stats


def classify_action(stats: WindowStats) -> Tuple[ActionLabel, float, str]:
    """
    Rule-based action classification from window statistics.

    Returns:
        (action_label, confidence, dominant_region)
    """
    # If visibility is too low, classify as idle
    if stats.avg_visible_fraction < 0.3:
        return ActionLabel.IDLE, 0.9, "none"

    # Key derived values
    avg_elbow = (stats.avg_left_elbow + stats.avg_right_elbow) / 2
    avg_shoulder = (stats.avg_left_shoulder + stats.avg_right_shoulder) / 2
    avg_knee = (stats.avg_left_knee + stats.avg_right_knee) / 2
    avg_hip = (stats.avg_left_hip + stats.avg_right_hip) / 2
    hands_low = stats.avg_wrist_y > stats.avg_shoulder_y + 0.1  # wrists below shoulders

    # ── WAIT: minimal upper-body motion, standing still ──
    # Low std of wrist position, arms roughly straight down
    if stats.std_wrist_y < 0.02 and stats.std_wrist_spread < 0.03:
        if avg_elbow > 140 and avg_shoulder < 30:
            return ActionLabel.WAIT, 0.75, "full_body"

    # ── INSPECT: one or both hands near face/eye level, relatively still ──
    # Wrists above shoulders, low motion
    if stats.avg_wrist_y < stats.avg_shoulder_y - 0.05 and stats.std_wrist_y < 0.03:
        if stats.std_wrist_spread < 0.04:
            return ActionLabel.INSPECT, 0.7, "upper_body"

    # ── GRASP: hands closing (elbow angle going from straight to bent)
    # Wrist spread increasing, arms bending
    if stats.std_wrist_spread > 0.05 and stats.avg_wrist_spread > 0.1:
        if avg_elbow < 120:
            conf = 0.65
            # Boost confidence with hand data: high grip_strength confirms grip
            if stats.has_hand_data and stats.avg_grip_strength > 0.6:
                conf = max(conf, 0.80 + 0.15 * stats.avg_grip_strength)
            return ActionLabel.GRASP, min(conf, 0.95), "upper_body"

    # ── REACH: one arm extended outward, high shoulder angle
    # Arms reaching away from body, shoulders elevated
    if avg_shoulder > 60:
        if hands_low or stats.std_wrist_y > 0.05:
            return ActionLabel.REACH, 0.6, "upper_body"

    # ── ASSEMBLE: both hands close together, moderate arm bend
    # Wrist spread small, elbows bent around 70-110 degrees
    if stats.avg_wrist_spread < 0.12 and avg_shoulder > 30:
        if 70 < avg_elbow < 130:
            return ActionLabel.ASSEMBLE, 0.6, "upper_body"

    # ── MOVE: large body displacement, legs active
    # Significant motion in hip/knee angles, high std in wrist position
    if stats.std_wrist_y > 0.06 or stats.standing_ratio < 0.5:
        return ActionLabel.MOVE, 0.55, "full_body"

    # ── RELEASE: enhanced with hand data if available
    if stats.std_wrist_spread > 0.05 and stats.avg_wrist_spread < 0.15:
        if avg_elbow > 120:
            conf = 0.65
            # Boost: low grip + high spread confirms release
            if stats.has_hand_data and stats.avg_grip_strength < 0.3 and stats.avg_finger_spread > 0.6:
                conf = max(conf, 0.80 + 0.15 * stats.avg_finger_spread)
            return ActionLabel.RELEASE, min(conf, 0.95), "upper_body"

    # ── Default: if arms are bent and hands are at mid-level, assume assembly work ──
    if 40 < avg_shoulder < 80 and 50 < avg_elbow < 140:
        return ActionLabel.ASSEMBLE, 0.4, "upper_body"

    # Fallback
    return ActionLabel.WAIT, 0.3, "full_body"
