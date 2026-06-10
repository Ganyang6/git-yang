"""
Hand landmark estimator using MediaPipe HandLandmarker.

Extracts 21-point hand landmarks and derives features:
  - grip_strength:  0=open hand, 1=fully closed fist
  - pinch_distance: thumb-index tip distance (0=pinched, ~1=open)
  - finger_spread:  0=closed, 1=fully spread
  - hand_visible:   bool, whether hand detection succeeded
  - handedness:     "Left" or "Right" for the primary detected hand
  - landmarks:      raw 21x3 keypoints (for future use)

Uses MediaPipe Tasks API (mp.tasks.vision.HandLandmarker).
"""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

try:
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python import vision as mp_vision
    from mediapipe import Image as MpImage, ImageFormat

    _HAS_MEDIAPIPE = True
except ImportError:
    mp_vision = None
    MpImage = None
    ImageFormat = None
    BaseOptions = None
    _HAS_MEDIAPIPE = False

logger = logging.getLogger(__name__)

# MediaPipe Hand landmark indices (0-20)
_LANDMARK_WRIST = 0
_LANDMARK_THUMB_TIP = 4
_LANDMARK_INDEX_TIP = 8
_LANDMARK_MIDDLE_TIP = 12
_LANDMARK_RING_TIP = 16
_LANDMARK_PINKY_TIP = 20

_FINGER_TIPS = [
    _LANDMARK_THUMB_TIP,
    _LANDMARK_INDEX_TIP,
    _LANDMARK_MIDDLE_TIP,
    _LANDMARK_RING_TIP,
    _LANDMARK_PINKY_TIP,
]

# Normalization constants (derived from empirical observation)
_GRIP_CLOSED_DIST = 0.05   # typical closed-fist avg tip-to-wrist distance
_GRIP_OPEN_DIST = 0.25     # typical open-hand avg tip-to-wrist distance
_PINCH_OPEN_DIST = 0.15    # typical open thumb-index distance
_SPREAD_OPEN_DIST = 0.12   # typical spread-finger adjacent tip distance

_MODEL_NAME = "hand_landmarker.task"
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
)


def _get_model_path() -> str:
    """Return local model path, downloading if necessary."""
    model_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "models"
    )
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, _MODEL_NAME)
    if not os.path.exists(model_path):
        logger.info("Downloading Hand Landmarker model from %s ...", _MODEL_URL)
        urllib.request.urlretrieve(_MODEL_URL, model_path)
        logger.info("Model downloaded to %s", model_path)
    return model_path


class HandEstimator:
    """
    MediaPipe HandLandmarker wrapper for extracting hand features.

    Usage:
        estimator = HandEstimator()
        features = estimator.extract_features(rgb_frame)
        # features -> dict or None
        estimator.close()
    """

    def __init__(
        self,
        max_num_hands: int = 2,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ):
        self._landmarker = None
        if not _HAS_MEDIAPIPE:
            raise ImportError(
                "mediapipe>=0.10.0 is required for HandEstimator. "
                "Install: pip install mediapipe>=0.10.0"
            )
        model_path = _get_model_path()
        base_options = BaseOptions(model_asset_path=model_path, delegate=BaseOptions.Delegate.CPU)
        options = mp_vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.IMAGE,
            num_hands=max_num_hands,
            min_hand_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
        logger.info(
            "HandEstimator initialized (max_num_hands=%d, model=%s)",
            max_num_hands, Path(model_path).name,
        )

    def extract_features(self, rgb_frame: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Process a single RGB frame and return hand-derived features.

        Args:
            rgb_frame: np.ndarray of shape (H, W, 3) in RGB order.

        Returns:
            dict with keys:
                grip_strength (float):  0=open hand, 1=fully closed fist
                pinch_distance (float): 0=pinched, ~1=fully open
                finger_spread (float):  0=closed, 1=fully spread
                hand_visible (bool):    True if a hand was detected
                handedness (str):       "Left" or "Right"
                landmarks (list):       21x3 keypoints [[x, y, z], ...]
            Returns None if no hand is detected.
        """
        # Validate and normalize frame before passing to MediaPipe
        if rgb_frame.dtype != np.uint8:
            rgb_frame = (rgb_frame * 255).astype(np.uint8) if rgb_frame.max() <= 1.0 else rgb_frame.astype(np.uint8)
        if not rgb_frame.flags.contiguous:
            rgb_frame = np.ascontiguousarray(rgb_frame)

        mp_image = MpImage(image_format=ImageFormat.SRGB, data=rgb_frame)
        result = self._landmarker.detect(mp_image)

        if not result or not result.hand_landmarks:
            return None

        # Take the primary hand (first detected)
        hand_landmarks = result.hand_landmarks[0]

        # Grip strength: avg of distances from finger tips to wrist.
        # Lower avg distance = more curled = higher grip_strength.
        wrist = hand_landmarks[_LANDMARK_WRIST]
        tip_distances = []
        for tip_idx in _FINGER_TIPS:
            tip = hand_landmarks[tip_idx]
            dist = np.sqrt(
                (tip.x - wrist.x) ** 2
                + (tip.y - wrist.y) ** 2
                + (tip.z - wrist.z) ** 2
            )
            tip_distances.append(dist)
        avg_dist = float(np.mean(tip_distances))

        # Normalize: typical closed ~0.05, open ~0.25
        raw_grip = (avg_dist - _GRIP_CLOSED_DIST) / (
            _GRIP_OPEN_DIST - _GRIP_CLOSED_DIST
        )
        grip_strength = 1.0 - min(max(raw_grip, 0.0), 1.0)

        # Pinch distance: thumb tip (4) to index tip (8)
        thumb_tip = hand_landmarks[_LANDMARK_THUMB_TIP]
        index_tip = hand_landmarks[_LANDMARK_INDEX_TIP]
        pinch_dist = float(np.sqrt(
            (thumb_tip.x - index_tip.x) ** 2
            + (thumb_tip.y - index_tip.y) ** 2
            + (thumb_tip.z - index_tip.z) ** 2
        ))
        # Normalize: pinched ~0.02, open ~0.15
        pinch_distance = min(pinch_dist / _PINCH_OPEN_DIST, 1.0)

        # Finger spread: avg of distances between adjacent finger tips
        spread_dists = []
        for i in range(4):
            t1 = hand_landmarks[_FINGER_TIPS[i]]
            t2 = hand_landmarks[_FINGER_TIPS[i + 1]]
            d = float(np.sqrt(
                (t1.x - t2.x) ** 2 + (t1.y - t2.y) ** 2
            ))
            spread_dists.append(d)
        avg_spread = float(np.mean(spread_dists))
        finger_spread = min(avg_spread / _SPREAD_OPEN_DIST, 1.0)

        # Handedness
        handedness = "Left"
        if result.handedness and len(result.handedness) > 0:
            category = result.handedness[0][0]
            handedness = category.category_name  # "Left" or "Right"

        # Raw landmarks (21x3) for future use
        landmarks = [[lm.x, lm.y, lm.z] for lm in hand_landmarks]

        return {
            "grip_strength": grip_strength,
            "pinch_distance": pinch_distance,
            "finger_spread": finger_spread,
            "hand_visible": True,
            "handedness": handedness,
            "landmarks": landmarks,
        }

    def close(self) -> None:
        """Release MediaPipe HandLandmarker resources."""
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None
