"""
Tests for OnnxActionClassifier.

Mocks OnnxSessionManager to test:
  - Sliding window buffer behavior
  - Preprocessing (frame stacking, shape transformation)
  - Postprocessing (softmax, label mapping, probabilities)
  - classify() with full sequence
  - add_frame() incremental mode
  - reset() clears state
  - Graceful degradation when unavailable
"""

from collections import deque
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services.onnx_action_classifier import (
    ACTION_CLASSES,
    OnnxActionClassifier,
    OnnxClassificationResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_classifier(
    available=True,
    window_size=5,
    confidence_threshold=0.7,
    slide_step=2,
):
    """Create a classifier with mocked OnnxSessionManager.

    OnnxActionClassifier imports OnnxSessionManager lazily inside __init__,
    so we patch the import path: 'onnxruntime.InferenceSession'.
    """
    with patch("onnxruntime.InferenceSession") as mock_ort_cls:
        mock_mgr = MagicMock()
        if available:
            mock_mgr.get_model_metadata.return_value = {
                "input_names": ["input"],
                "input_shapes": {"input": [1, 3, 5, 33]},
                "output_names": ["output"],
                "output_shapes": {"output": [1, 7]},
                "model_info": {},
            }
            mock_mgr._session = MagicMock()
        else:
            mock_mgr._session = None
            mock_mgr.get_model_metadata.return_value = {}
        mock_ort_cls.return_value = MagicMock()  # Not actually called when mocked
        mock_ort_cls.return_value = mock_mgr

        # Directly construct without triggering the lazy import
        classifier = object.__new__(OnnxActionClassifier)
        classifier._window_size = window_size
        classifier._confidence_threshold = confidence_threshold
        classifier._slide_step = slide_step
        classifier._frame_buffer = deque(maxlen=window_size)
        classifier._frames_since_last_inference = 0
        classifier._session_mgr = mock_mgr
        classifier._available = available
        classifier._metadata = mock_mgr.get_model_metadata() if available else {}

    return classifier


def _make_random_frame(shape=(33, 3)):
    rng = np.random.default_rng(seed=42)
    return rng.random(shape).astype(np.float32)


def _softmax(logits):
    exp = np.exp(logits - np.max(logits))
    return exp / exp.sum()


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_available_when_model_loaded(self):
        clf = _make_classifier(available=True)
        assert clf.is_available is True

    def test_unavailable_when_model_not_loaded(self):
        clf = _make_classifier(available=False)
        assert clf.is_available is False

    def test_model_info_available(self):
        clf = _make_classifier(available=True)
        info = clf.model_info
        assert info["input_names"] == ["input"]

    def test_model_info_unavailable(self):
        clf = _make_classifier(available=False)
        # model_info returns {} when session_mgr metadata is empty
        assert clf.model_info == {}


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_buffer(self):
        clf = _make_classifier(available=True, window_size=5)
        frame = _make_random_frame()
        for _ in range(3):
            clf.add_frame(frame)
        assert len(clf._frame_buffer) > 0
        clf.reset()
        assert len(clf._frame_buffer) == 0
        assert clf._frames_since_last_inference == 0


# ---------------------------------------------------------------------------
# add_frame (Sliding Window)
# ---------------------------------------------------------------------------


class TestAddFrame:
    def test_returns_none_when_buffer_not_full(self):
        clf = _make_classifier(available=True, window_size=5, slide_step=2)
        frame = _make_random_frame()
        result = clf.add_frame(frame)
        assert result is None

    def test_returns_none_when_slide_step_not_reached(self):
        clf = _make_classifier(available=True, window_size=5, slide_step=2)
        frame = _make_random_frame()
        # Setup mock predict for when inference does run
        clf._session_mgr.predict = MagicMock(
            return_value=np.array([[1, 0, 0, 0, 0, 0, 0]]),
        )
        # Add exactly 5 frames (buffer full)
        for _ in range(5):
            result = clf.add_frame(frame)
        # frames_since_last_inference was reset to 0 by the first inference
        # Now add 1 more frame: counter=1 < 2, should not trigger
        result = clf.add_frame(frame)
        assert result is None

    def test_returns_result_when_buffer_full_and_slide_step_reached(self):
        clf = _make_classifier(available=True, window_size=3, slide_step=1)

        # Setup mock predict to return logits
        logits = np.array([[1.0, 0.5, 0.3, 0.2, 0.1, 0.05, 0.01]])
        clf._session_mgr.predict = MagicMock(return_value=logits)

        frame = _make_random_frame()
        # Fill buffer (3 frames)
        for _ in range(2):
            clf.add_frame(frame)
        result = clf.add_frame(frame)  # 3rd frame triggers inference
        assert result is not None
        assert isinstance(result, OnnxClassificationResult)

    def test_returns_none_when_unavailable(self):
        clf = _make_classifier(available=False, window_size=3)
        frame = _make_random_frame()
        for _ in range(5):
            result = clf.add_frame(frame)
        assert result is None

    def test_normalizes_4d_landmarks_to_3d(self):
        """Landmarks with (33, 4) should be trimmed to (33, 3)."""
        clf = _make_classifier(available=True, window_size=2, slide_step=1)
        clf._session_mgr.predict = MagicMock(
            return_value=np.array([[1, 0, 0, 0, 0, 0, 0]]),
        )

        frame_4d = _make_random_frame((33, 4))
        clf.add_frame(frame_4d)
        # Check that stored frame has shape (33, 3)
        stored = clf._frame_buffer[0]
        assert stored.shape == (33, 3)


# ---------------------------------------------------------------------------
# classify (Direct Sequence)
# ---------------------------------------------------------------------------


class TestClassify:
    def test_returns_none_when_unavailable(self):
        clf = _make_classifier(available=False)
        frames = [_make_random_frame() for _ in range(5)]
        result = clf.classify(frames)
        assert result is None

    def test_returns_none_when_sequence_too_short(self):
        clf = _make_classifier(available=True, window_size=5)
        frames = [_make_random_frame() for _ in range(3)]
        result = clf.classify(frames)
        assert result is None

    def test_returns_none_for_empty_sequence(self):
        clf = _make_classifier(available=True)
        result = clf.classify([])
        assert result is None

    def test_returns_result_with_correct_label(self):
        clf = _make_classifier(available=True, window_size=3)

        # High confidence for class 2 (grasp)
        logits = np.array([[0.01, 0.01, 0.9, 0.03, 0.02, 0.02, 0.01]])
        clf._session_mgr.predict = MagicMock(return_value=logits)

        frames = [_make_random_frame() for _ in range(3)]
        result = clf.classify(frames)

        assert result is not None
        assert result.label == "grasp"
        assert result.label_index == 2
        assert result.confidence == pytest.approx(0.9, abs=0.05)
        assert "grasp" in result.probabilities

    def test_uses_last_window_size_frames(self):
        """Should use only the last window_size frames."""
        clf = _make_classifier(available=True, window_size=3)
        clf._session_mgr.predict = MagicMock(
            return_value=np.array([[1, 0, 0, 0, 0, 0, 0]]),
        )

        frames = [_make_random_frame() for _ in range(10)]
        clf.classify(frames)

        # Check that predict was called with shape (1, 3, 3, 33)
        call_arg = clf._session_mgr.predict.call_args[0][0]
        assert call_arg.shape == (1, 3, 3, 33)

    def test_inference_error_returns_none(self):
        clf = _make_classifier(available=True, window_size=3)
        clf._session_mgr.predict = MagicMock(side_effect=RuntimeError("OOM"))

        frames = [_make_random_frame() for _ in range(3)]
        result = clf.classify(frames)
        assert result is None


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------


class TestPreprocess:
    def test_output_shape(self):
        clf = _make_classifier(available=True, window_size=5)
        frames = [_make_random_frame((33, 3)) for _ in range(5)]
        tensor = clf._preprocess(frames)
        assert tensor.shape == (1, 3, 5, 33)
        assert tensor.dtype == np.float32

    def test_output_shape_single_channel(self):
        """Frames already (33, 3) stay as 3 channels."""
        clf = _make_classifier(available=True, window_size=4)
        frames = [np.zeros((33, 3)) for _ in range(4)]
        tensor = clf._preprocess(frames)
        assert tensor.shape == (1, 3, 4, 33)


# ---------------------------------------------------------------------------
# Postprocessing
# ---------------------------------------------------------------------------


class TestPostprocess:
    def test_softmax_applied_to_logits(self):
        clf = _make_classifier(available=True)
        logits = np.array([[5.0, 3.0, 2.0, 1.0, 0.5, 0.3, 0.1]])
        result = clf._postprocess(logits)
        assert result.label == "reach"
        assert result.label_index == 0
        assert result.confidence > 0.8  # Should be high after softmax

    def test_already_probabilities(self):
        """Output already sums to ~1.0, softmax should not change much."""
        clf = _make_classifier(available=True)
        probs = np.array([[0.4, 0.3, 0.1, 0.08, 0.05, 0.04, 0.03]])
        result = clf._postprocess(probs)
        assert result.label == "reach"
        assert result.confidence == pytest.approx(0.4, abs=0.01)

    def test_all_probabilities_dict(self):
        clf = _make_classifier(available=True)
        probs = np.array([[0.5, 0.2, 0.1, 0.05, 0.05, 0.05, 0.05]])
        result = clf._postprocess(probs)
        for cls_name in ACTION_CLASSES:
            assert cls_name in result.probabilities

    def test_fallback_label_for_unknown_index(self):
        """If label_index >= len(ACTION_CLASSES), use class_{index}."""
        clf = _make_classifier(available=True)
        # Output with 10 classes (more than ACTION_CLASSES)
        probs = np.array([[0.1] * 7 + [0.2, 0.1, 0.0]])
        result = clf._postprocess(probs)
        # argmax should be index 7 (value 0.2)
        assert result.label_index == 7
        assert result.label == "class_7"


# ---------------------------------------------------------------------------
# ACTION_CLASSES
# ---------------------------------------------------------------------------


class TestActionClasses:
    def test_seven_classes(self):
        assert len(ACTION_CLASSES) == 7

    def test_expected_class_names(self):
        expected = {"reach", "move", "grasp", "hold", "assemble", "inspect", "release"}
        assert set(ACTION_CLASSES) == expected
