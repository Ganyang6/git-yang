"""
Tests for OnnxSessionManager.

Patches onnxruntime (imported lazily inside _load_model) to test:
  - Model loading with / without integrity check
  - Inference (predict / predict_with_input_names)
  - Hot-swap (reload_model)
  - Thread safety (lock behavior)
  - Metadata extraction
  - Close / resource cleanup
  - Missing model file handling
"""

import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services.onnx_session_manager import OnnxSessionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(model_path="dummy.onnx", expected_checksum=None):
    return OnnxSessionManager(model_path, expected_checksum=expected_checksum)


def _create_temp_model_file(content=b"fake-onnx-model-data"):
    fd, path = tempfile.mkstemp(suffix=".onnx", prefix="test_model_")
    os.write(fd, content)
    os.close(fd)
    return path


def _compute_checksum(path):
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            sha.update(block)
    return sha.hexdigest()


def _mock_ort_session(
    input_names=None, input_shapes=None, output_names=None, output_shapes=None,
    custom_metadata=None, run_output=None,
):
    """Create a mock ONNX InferenceSession."""
    input_names = input_names or ["input_data"]
    input_shapes = input_shapes or {n: [1, 3, 30, 33] for n in input_names}
    output_names = output_names or ["output"]
    output_shapes = output_shapes or {n: [1, 7] for n in output_names}

    inputs = []
    for name in input_names:
        inp = MagicMock()
        inp.name = name
        inp.shape = input_shapes[name]
        inp.type = "tensor(float)"
        inputs.append(inp)

    outputs = []
    for name in output_names:
        out = MagicMock()
        out.name = name
        out.shape = output_shapes[name]
        out.type = "tensor(float)"
        outputs.append(out)

    mock_session = MagicMock()
    mock_session.get_inputs.return_value = inputs
    mock_session.get_outputs.return_value = outputs
    mock_session.get_modelmeta.return_value = MagicMock(
        custom_metadata_map=custom_metadata or {},
    )
    mock_session.run.return_value = run_output or [np.array([[0.1] * 7])]
    return mock_session


def _patch_ort():
    """Context manager patches for onnxruntime (only InferenceSession and SessionOptions)."""
    return patch("onnxruntime.InferenceSession"), \
           patch("onnxruntime.SessionOptions")


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    def test_init_with_nonexistent_path(self):
        mgr = _make_manager(model_path="C:/nonexistent/model.onnx")
        assert mgr.is_ready is False
        assert mgr.model_path == "C:\\nonexistent\\model.onnx"

    def test_init_lock_created(self):
        mgr = _make_manager()
        assert mgr._lock is not None


# ---------------------------------------------------------------------------
# Model Loading
# ---------------------------------------------------------------------------


class TestModelLoading:
    def test_ensure_loaded_creates_session(self):
        model_path = _create_temp_model_file()
        try:
            mock_session = _mock_ort_session()
            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2 as mock_sess_opt:
                mock_inf.return_value = mock_session
                mock_sess_opt.return_value = MagicMock()
                mgr = OnnxSessionManager(model_path)
                assert mgr.ensure_loaded() is True
                assert mgr.is_ready is True
                mock_inf.assert_called_once()
        finally:
            os.unlink(model_path)

    def test_ensure_loaded_no_file(self):
        mgr = OnnxSessionManager("C:/nonexistent/model.onnx")
        assert mgr.ensure_loaded() is False

    def test_ensure_loaded_import_error(self):
        model_path = _create_temp_model_file()
        try:
            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2:
                mock_inf.side_effect = ImportError("no onnxruntime")
                mgr = OnnxSessionManager(model_path)
                assert mgr.ensure_loaded() is False
        finally:
            os.unlink(model_path)

    def test_ensure_loaded_runtime_error(self):
        model_path = _create_temp_model_file()
        try:
            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2:
                mock_inf.side_effect = RuntimeError("corrupt model")
                mgr = OnnxSessionManager(model_path)
                assert mgr.ensure_loaded() is False
        finally:
            os.unlink(model_path)

    def test_ensure_loaded_idempotent(self):
        model_path = _create_temp_model_file()
        try:
            mock_session = _mock_ort_session()
            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2 as mock_sess_opt:
                mock_inf.return_value = mock_session
                mock_sess_opt.return_value = MagicMock()
                mgr = OnnxSessionManager(model_path)
                mgr.ensure_loaded()
                mgr.ensure_loaded()
                assert mock_inf.call_count == 1
        finally:
            os.unlink(model_path)


# ---------------------------------------------------------------------------
# Integrity Check
# ---------------------------------------------------------------------------


class TestIntegrityCheck:
    def test_verify_integrity_no_checksum(self):
        mgr = _make_manager(expected_checksum=None)
        assert mgr.verify_integrity() is True

    def test_verify_integrity_matching_checksum(self):
        model_path = _create_temp_model_file(b"test-model-content")
        try:
            checksum = _compute_checksum(model_path)
            mgr = OnnxSessionManager(model_path, expected_checksum=checksum)
            assert mgr.verify_integrity() is True
        finally:
            os.unlink(model_path)

    def test_verify_integrity_mismatch(self):
        model_path = _create_temp_model_file(b"test-model-content")
        try:
            mgr = OnnxSessionManager(model_path, expected_checksum="0" * 64)
            assert mgr.verify_integrity() is False
        finally:
            os.unlink(model_path)

    def test_verify_integrity_missing_file(self):
        mgr = OnnxSessionManager("C:/nonexistent/model.onnx", expected_checksum="0" * 64)
        assert mgr.verify_integrity() is False

    def test_verify_integrity_custom_checksum_override(self):
        model_path = _create_temp_model_file(b"content")
        try:
            mgr = OnnxSessionManager(model_path)
            actual = _compute_checksum(model_path)
            assert mgr.verify_integrity(expected_checksum=actual) is True
        finally:
            os.unlink(model_path)


# ---------------------------------------------------------------------------
# Predict
# ---------------------------------------------------------------------------


class TestPredict:
    def test_predict_returns_output(self):
        model_path = _create_temp_model_file()
        try:
            expected_output = np.array([[0.1, 0.2, 0.3, 0.15, 0.05, 0.1, 0.1]])
            mock_session = _mock_ort_session(run_output=[expected_output])
            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2 as mock_sess_opt:
                mock_inf.return_value = mock_session
                mock_sess_opt.return_value = MagicMock()
                mgr = OnnxSessionManager(model_path)
                result = mgr.predict(np.zeros((1, 3, 30, 33), dtype=np.float32))
                assert result is not None
                np.testing.assert_array_equal(result, expected_output)
        finally:
            os.unlink(model_path)

    def test_predict_without_loaded_model(self):
        mgr = OnnxSessionManager("C:/nonexistent/model.onnx")
        result = mgr.predict(np.zeros((1, 3, 30, 33)))
        assert result is None

    def test_predict_inference_error(self):
        model_path = _create_temp_model_file()
        try:
            mock_session = _mock_ort_session()
            mock_session.run.side_effect = RuntimeError("inference failed")
            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2 as mock_sess_opt:
                mock_inf.return_value = mock_session
                mock_sess_opt.return_value = MagicMock()
                mgr = OnnxSessionManager(model_path)
                result = mgr.predict(np.zeros((1, 3, 30, 33)))
                assert result is None
        finally:
            os.unlink(model_path)

    def test_predict_with_input_names(self):
        model_path = _create_temp_model_file()
        try:
            expected_output = np.array([[1, 2, 3]])
            mock_session = _mock_ort_session(run_output=[expected_output])
            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2 as mock_sess_opt:
                mock_inf.return_value = mock_session
                mock_sess_opt.return_value = MagicMock()
                mgr = OnnxSessionManager(model_path)
                result = mgr.predict_with_input_names({"x": np.zeros((1, 10))})
                assert result is not None
                mock_session.run.assert_called_once()
                call_args = mock_session.run.call_args
                assert call_args[0][0] is None  # No output names filter
                assert "x" in call_args[0][1]
        finally:
            os.unlink(model_path)


# ---------------------------------------------------------------------------
# Hot-Swap
# ---------------------------------------------------------------------------


class TestHotSwap:
    def test_reload_model_success(self):
        old_path = _create_temp_model_file(b"old-model")
        new_path = _create_temp_model_file(b"new-model")
        try:
            call_count = [0]
            def make_session(*args, **kwargs):
                call_count[0] += 1
                meta = {"version": "old"} if call_count[0] == 1 else {"version": "new"}
                return _mock_ort_session(custom_metadata=meta)

            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2 as mock_sess_opt:
                mock_inf.side_effect = make_session
                mock_sess_opt.return_value = MagicMock()
                mgr = OnnxSessionManager(old_path)
                mgr.ensure_loaded()
                assert mgr.is_ready is True

                result = mgr.reload_model(new_path)
                assert result is True
                assert mgr.model_path == str(Path(new_path))
                assert mgr.is_ready is True
        finally:
            os.unlink(old_path)
            os.unlink(new_path)

    def test_reload_model_missing_file(self):
        old_path = _create_temp_model_file(b"old")
        try:
            mgr = OnnxSessionManager(old_path)
            result = mgr.reload_model("C:/nonexistent/new.onnx")
            assert result is False
        finally:
            os.unlink(old_path)

    def test_reload_model_failure_keeps_old(self):
        old_path = _create_temp_model_file(b"old-model")
        new_path = _create_temp_model_file(b"bad-new-model")
        try:
            call_count = [0]
            def make_session(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return _mock_ort_session()
                raise RuntimeError("new model corrupt")

            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2 as mock_sess_opt:
                mock_inf.side_effect = make_session
                mock_sess_opt.return_value = MagicMock()
                mgr = OnnxSessionManager(old_path)
                mgr.ensure_loaded()

                result = mgr.reload_model(new_path)
                assert result is False
                assert mgr.is_ready is True  # Old model still active
        finally:
            os.unlink(old_path)
            os.unlink(new_path)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_get_metadata_without_model(self):
        mgr = OnnxSessionManager("C:/nonexistent/model.onnx")
        meta = mgr.get_model_metadata()
        assert meta == {}

    def test_get_metadata_with_model(self):
        model_path = _create_temp_model_file()
        try:
            mock_session = _mock_ort_session(
                input_names=["input_data"],
                input_shapes={"input_data": [1, 3, 30, 33]},
                output_names=["output"],
                output_shapes={"output": [1, 7]},
                custom_metadata={"author": "test"},
            )
            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2 as mock_sess_opt:
                mock_inf.return_value = mock_session
                mock_sess_opt.return_value = MagicMock()
                mgr = OnnxSessionManager(model_path)
                mgr.ensure_loaded()
                meta = mgr.get_model_metadata()
                assert meta["input_names"] == ["input_data"]
                assert meta["input_shapes"]["input_data"] == [1, 3, 30, 33]
                assert meta["output_names"] == ["output"]
                assert meta["model_info"]["author"] == "test"
        finally:
            os.unlink(model_path)


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_releases_session(self):
        model_path = _create_temp_model_file()
        try:
            mock_session = _mock_ort_session()
            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2 as mock_sess_opt:
                mock_inf.return_value = mock_session
                mock_sess_opt.return_value = MagicMock()
                mgr = OnnxSessionManager(model_path)
                mgr.ensure_loaded()
                assert mgr.is_ready is True

                mgr.close()
                assert mgr.is_ready is False
                assert mgr._session is None
        finally:
            os.unlink(model_path)

    def test_close_without_session(self):
        mgr = OnnxSessionManager("C:/nonexistent/model.onnx")
        mgr.close()  # Should not raise


# ---------------------------------------------------------------------------
# P1-2b: _inference_fail_count resets on success, threshold alert fires once
# ---------------------------------------------------------------------------

import logging


class TestInferenceFailCountReset:
    """P1-2: Inference fail counter must reset on success and threshold
    alert must fire only once (at == threshold), not every failure."""

    def test_counter_resets_on_successful_predict(self):
        """After a successful predict, counter must reset to 0."""
        model_path = _create_temp_model_file()
        try:
            mock_session = _mock_ort_session(
                run_output=[np.array([[0.1] * 7])]
            )
            # Make first call fail, second succeed
            mock_session.run.side_effect = [
                RuntimeError("inference failed"),
                [np.array([[0.1] * 7])],
            ]
            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2 as mock_sess_opt:
                mock_inf.return_value = mock_session
                mock_sess_opt.return_value = MagicMock()
                mgr = OnnxSessionManager(model_path)

                # First call: fail
                result = mgr.predict(np.zeros((1, 3, 30, 33)))
                assert result is None
                assert mgr._inference_fail_count == 1

                # Second call: succeed
                result = mgr.predict(np.zeros((1, 3, 30, 33)))
                assert result is not None
                assert mgr._inference_fail_count == 0, (
                    "Counter must reset on successful inference"
                )
        finally:
            os.unlink(model_path)

    def test_counter_resets_on_successful_predict_with_input_names(self):
        """Counter must also reset on predict_with_input_names success."""
        model_path = _create_temp_model_file()
        try:
            mock_session = _mock_ort_session(
                run_output=[np.array([[0.1] * 7])]
            )
            mock_session.run.side_effect = [
                RuntimeError("inference failed"),
                [np.array([[0.1] * 7])],
            ]
            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2 as mock_sess_opt:
                mock_inf.return_value = mock_session
                mock_sess_opt.return_value = MagicMock()
                mgr = OnnxSessionManager(model_path)

                mgr.predict_with_input_names({"x": np.zeros((1, 10))})
                assert mgr._inference_fail_count == 1

                mgr.predict_with_input_names({"x": np.zeros((1, 10))})
                assert mgr._inference_fail_count == 0
        finally:
            os.unlink(model_path)

    def test_threshold_alert_fires_only_once(self, caplog):
        """Threshold alert must fire at exactly == threshold, not >=."""
        model_path = _create_temp_model_file()
        try:
            mgr = OnnxSessionManager(model_path)
            mgr._INFERENCE_FAIL_THRESHOLD = 3  # Low for testing

            mock_session = _mock_ort_session()
            mock_session.run.side_effect = RuntimeError("inference failed")

            p1, p2 = _patch_ort()
            with p1 as mock_inf, p2 as mock_sess_opt:
                mock_inf.return_value = mock_session
                mock_sess_opt.return_value = MagicMock()

                # 5 failures, threshold=3
                for _ in range(5):
                    mgr.predict(np.zeros((1, 3, 30, 33)))

            threshold_alerts = [
                r for r in caplog.records
                if "threshold" in r.message.lower() and r.levelno == logging.ERROR
            ]
            assert len(threshold_alerts) == 1, (
                f"Threshold alert should fire exactly once, got {len(threshold_alerts)}"
            )
        finally:
            os.unlink(model_path)
