"""ONNX-based action classifier for manufacturing gesture recognition.

Wraps OnnxSessionManager with sliding window buffer, input preprocessing
(MediaPipe 33 keypoints -> model input format), and output post-processing
(Softmax probabilities -> action class labels).

Integrates with the existing ActionClassifier as an optional enhancement:
  - If ONNX model exists: use ONNX, fallback to rules if confidence < threshold
  - If ONNX model missing: use rule-based classifier only

7 action classes:
  0: reach, 1: move, 2: grasp, 3: hold, 4: assemble, 5: inspect, 6: release
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Action class labels
ACTION_CLASSES = [
    "reach", "move", "grasp", "hold", "assemble", "inspect", "release",
]


@dataclass
class OnnxClassificationResult:
    """Result from ONNX action classification."""

    label: str
    label_index: int
    confidence: float
    probabilities: Dict[str, float]


class OnnxActionClassifier:
    """ONNX-based action classifier with sliding window buffer.

    Usage:
        classifier = OnnxActionClassifier("model.onnx")
        result = classifier.classify(landmarks_sequence)
        if result.confidence >= threshold:
            return result.label
    """

    def __init__(
        self,
        model_path: str,
        window_size: int = 30,
        confidence_threshold: float = 0.7,
        slide_step: int = 10,
    ):
        """Initialize classifier.

        Args:
            model_path: Path to ONNX model file.
            window_size: Number of frames per inference window.
            confidence_threshold: Minimum confidence to trust ONNX result.
            slide_step: Frames to slide after each inference.
        """
        from app.services.onnx_session_manager import OnnxSessionManager

        self._window_size = window_size
        self._confidence_threshold = confidence_threshold
        self._slide_step = slide_step
        self._frame_buffer: deque = deque(maxlen=window_size)
        self._frames_since_last_inference = 0

        try:
            self._session_mgr = OnnxSessionManager(model_path)
            self._metadata = self._session_mgr.get_model_metadata()
            self._available = self._session_mgr._session is not None
        except Exception as e:
            logger.error("ONNX classifier unavailable: %s", e)
            self._session_mgr = None
            self._metadata = {}
            self._available = False

    @property
    def is_available(self) -> bool:
        """Whether the ONNX model is loaded and ready."""
        return self._available

    @property
    def model_info(self) -> dict:
        """Get model metadata."""
        if self._session_mgr:
            return self._session_mgr.get_model_metadata()
        return {"loaded": False}

    def reset(self) -> None:
        """Clear the frame buffer."""
        self._frame_buffer.clear()
        self._frames_since_last_inference = 0

    def add_frame(self, landmarks: np.ndarray) -> Optional[OnnxClassificationResult]:
        """Add a single frame and attempt classification.

        Args:
            landmarks: numpy array of shape (33, 3) or (33, 4) with
                      x, y, z (and optionally visibility).

        Returns:
            OnnxClassificationResult if inference was performed and
            buffer was full, None otherwise.
        """
        if not self._available:
            return None

        # Normalize landmarks to (33, 3) - drop visibility if present
        frame = landmarks[:, :3] if landmarks.shape[-1] > 3 else landmarks

        self._frame_buffer.append(frame)
        self._frames_since_last_inference += 1

        # Only run inference when buffer is full and enough frames have slid
        if len(self._frame_buffer) < self._window_size:
            return None
        if self._frames_since_last_inference < self._slide_step:
            return None

        self._frames_since_last_inference = 0
        frames = list(self._frame_buffer)
        return self.classify(frames)

    def classify(
        self, landmarks_sequence: List[np.ndarray],
    ) -> Optional[OnnxClassificationResult]:
        """Classify a sequence of landmarks directly.

        Args:
            landmarks_sequence: List of frames, each (33, 3).

        Returns:
            OnnxClassificationResult, or None if unavailable.
        """
        if not self._available or not landmarks_sequence:
            return None

        # Use the last window_size frames
        frames = landmarks_sequence[-self._window_size:]
        if len(frames) < self._window_size:
            return None

        # Stack into (T, V, C)
        input_tensor = self._preprocess(frames)

        try:
            output = self._session_mgr.predict(input_tensor)
            return self._postprocess(output)
        except Exception as e:
            logger.error("ONNX inference failed: %s", e)
            return None

    def _preprocess(self, frames: List[np.ndarray]) -> np.ndarray:
        """Preprocess landmark sequence into model input format.

        Converts from list of (V, C) frames to model input shape.
        Default: (1, C, T, V) where C=3 (xyz), T=frames, V=33 (keypoints).

        Custom shapes should override this method.
        """
        # Stack frames: (T, V, C) -> (1, C, T, V)
        data = np.stack(frames, axis=0)  # (T, V, C)
        data = np.transpose(data, (2, 0, 1))  # (C, T, V)
        data = np.expand_dims(data, axis=0)  # (1, C, T, V)
        return data.astype(np.float32)

    def _postprocess(self, output: np.ndarray) -> OnnxClassificationResult:
        """Convert model output to classification result.

        Args:
            output: Raw model output, shape (1, num_classes).

        Returns:
            OnnxClassificationResult with label, confidence, and probabilities.
        """
        probs = output[0]

        # Softmax if output is logits (not already probabilities)
        if probs.min() < 0 or probs.max() > 1.0 or abs(probs.sum() - 1.0) > 0.01:
            exp_probs = np.exp(probs - probs.max())
            probs = exp_probs / exp_probs.sum()

        label_idx = int(np.argmax(probs))
        confidence = float(probs[label_idx])

        prob_dict = {}
        for i, cls_name in enumerate(ACTION_CLASSES):
            if i < len(probs):
                prob_dict[cls_name] = round(float(probs[i]), 4)

        return OnnxClassificationResult(
            label=ACTION_CLASSES[label_idx] if label_idx < len(ACTION_CLASSES) else f"class_{label_idx}",
            label_index=label_idx,
            confidence=confidence,
            probabilities=prob_dict,
        )

    def close(self) -> None:
        """Release ONNX session resources."""
        if self._session_mgr:
            self._session_mgr.close()
            self._available = False
