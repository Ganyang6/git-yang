"""TDD: ST-GCN action classification model."""
import numpy as np
import pytest


def _make_model():
    from app.ml.stgcn_model import STGCNClassifier
    return STGCNClassifier()


def test_stgcn_can_classify_skeleton_sequence():
    """
    ST-GCN should classify a (C, T, V, M) skeleton sequence
    into one of the action classes.

    Shape convention: (C, T, V, M) = (3, T, 33, 1)
      C: x, y, confidence
      T: temporal frames
      V: 33 MediaPipe landmarks
      M: 1 person
    """
    model = _make_model()
    mock_sequence = np.random.randn(3, 10, 33, 1).astype(np.float32)
    result = model.predict(mock_sequence)
    assert "action" in result
    assert "confidence" in result
    assert 0.0 <= result["confidence"] <= 1.0


def test_stgcn_short_sequence_returns_default():
    """
    P1.1: T < 4 should return a default low-confidence result
    instead of crashing in MaxPool2d layers.
    """
    model = _make_model()
    for t in [1, 2, 3]:
        mock_sequence = np.random.randn(3, t, 33, 1).astype(np.float32)
        result = model.predict(mock_sequence)
        assert result["action"] == "unknown"
        assert result["confidence"] == 0.0
        assert result["logits"] is None


def test_stgcn_predict_wrong_ndim_raises():
    """predict() should raise ValueError for non-4D input."""
    model = _make_model()
    # 5D input is not valid for single predict
    bad = np.random.randn(1, 3, 10, 33, 1).astype(np.float32)
    with pytest.raises(ValueError, match="Expected 4D input"):
        model.predict(bad)


def test_stgcn_predict_batch_normal():
    """predict_batch() should classify a batch of sequences."""
    model = _make_model()
    batch = np.random.randn(2, 3, 10, 33, 1).astype(np.float32)
    results = model.predict_batch(batch)
    assert len(results) == 2
    for r in results:
        assert "action" in r
        assert "confidence" in r
        assert 0.0 <= r["confidence"] <= 1.0


def test_stgcn_predict_batch_wrong_dim():
    """
    P1.2: predict_batch() should raise ValueError for
    non-5D input.
    """
    model = _make_model()
    # 4D input (no batch dim)
    bad_4d = np.random.randn(3, 10, 33, 1).astype(np.float32)
    with pytest.raises(ValueError, match="Expected 5D input"):
        model.predict_batch(bad_4d)

    # 3D input
    bad_3d = np.random.randn(10, 33, 1).astype(np.float32)
    with pytest.raises(ValueError, match="Expected 5D input"):
        model.predict_batch(bad_3d)
