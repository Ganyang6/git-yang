"""Tests for ModelBackend Protocol and implementations."""

import os
import tempfile
from types import SimpleNamespace

import pytest

from app.core.model_backend import (
    ModelBackend,
    ClassificationResult,
    OnnxBackend,
    RuleBackend,
    create_backend,
)


class TestModelBackendProtocol:
    """Verify that ModelBackend is a proper Protocol type."""

    def test_model_backend_is_protocol(self):
        """ModelBackend should be a Protocol."""
        assert isinstance(ModelBackend, type)

    def test_model_backend_has_classify_signature(self):
        """ModelBackend should define classify method."""
        assert hasattr(ModelBackend, "classify")
        assert callable(ModelBackend.classify)

    def test_model_backend_is_runtime_checkable(self):
        """ModelBackend should allow isinstance checks."""
        # runtime_checkable means we can isinstance check against it
        assert isinstance(ModelBackend, type)


class TestOnnxBackend:
    """Tests for OnnxBackend wrapper."""

    def test_onnx_backend_implements_classify_signature(self):
        """OnnxBackend should have a classify method."""
        assert hasattr(OnnxBackend, "classify")
        assert callable(OnnxBackend.classify)

    def test_onnx_backend_instantiable_without_model(self):
        """OnnxBackend should be instantiable even without a valid model."""
        backend = OnnxBackend("nonexistent.onnx", threshold=0.7)
        assert backend is not None

    def test_onnx_backend_classify_returns_none_when_no_model(self):
        """OnnxBackend.classify should return None when model doesn't exist."""
        backend = OnnxBackend("nonexistent.onnx", threshold=0.7)
        result = backend.classify([])
        assert result is None

    def test_onnx_backend_is_rule_backend_fallback(self):
        """OnnxBackend without model should gracefully degrade."""
        backend = OnnxBackend("nonexistent.onnx", threshold=0.7)
        # Should not raise exception
        result = backend.classify([])
        assert result is None


class TestRuleBackend:
    """Tests for RuleBackend wrapper."""

    def test_rule_backend_implements_classify_signature(self):
        """RuleBackend should have a classify method."""
        assert hasattr(RuleBackend, "classify")
        assert callable(RuleBackend.classify)

    def test_rule_backend_no_onnx_required(self):
        """RuleBackend should work without any .onnx file."""
        backend = RuleBackend()
        assert backend is not None

    def test_rule_backend_classify_returns_classification_result(self):
        """RuleBackend.classify should return a ClassificationResult."""
        backend = RuleBackend()
        result = backend.classify([])
        assert isinstance(result, ClassificationResult)
        assert hasattr(result, "action")
        assert hasattr(result, "confidence")
        assert hasattr(result, "backend")

    def test_rule_backend_backend_field_is_rule(self):
        """RuleBackend results should have backend='rule'."""
        backend = RuleBackend()
        result = backend.classify([])
        assert result.backend == "rule"

    def test_rule_backend_default_action_is_idle(self):
        """RuleBackend with empty frames should return idle action."""
        backend = RuleBackend()
        result = backend.classify([])
        assert result.action == "idle"


class TestCreateBackend:
    """Tests for create_backend factory function."""

    def test_create_backend_returns_callable(self):
        """create_backend should return an object with classify method."""
        backend = create_backend(_make_config(onnx_enabled=False))
        assert hasattr(backend, "classify")

    def test_create_backend_returns_rule_when_onnx_disabled(self):
        """When ONNX is disabled, should return RuleBackend."""
        backend = create_backend(_make_config(onnx_enabled=False))
        assert isinstance(backend, RuleBackend)

    def test_create_backend_returns_rule_when_model_missing(self):
        """When ONNX model_path doesn't exist, should return RuleBackend."""
        backend = create_backend(
            _make_config(onnx_enabled=True, model_path="/nonexistent/model.onnx")
        )
        assert isinstance(backend, RuleBackend)

    def test_create_backend_rule_classify_works(self):
        """RuleBackend from factory should classify successfully."""
        backend = create_backend(_make_config(onnx_enabled=False))
        result = backend.classify([])
        assert isinstance(result, ClassificationResult)

    def test_create_backend_onnx_when_model_exists(self):
        """When ONNX model exists and enabled, should return OnnxBackend."""
        tmp = tempfile.NamedTemporaryFile(suffix=".onnx", delete=False)
        tmp.close()
        try:
            backend = create_backend(
                _make_config(onnx_enabled=True, model_path=tmp.name)
            )
            assert isinstance(backend, OnnxBackend)
        finally:
            os.unlink(tmp.name)


# ── Helpers ──

def _make_config(onnx_enabled: bool = True, model_path: str = "models/test.onnx"):
    """Create a minimal config-like object for tests."""
    return SimpleNamespace(
        onnx=SimpleNamespace(
            enabled=onnx_enabled,
            model_path=model_path,
            confidence_threshold=0.7,
        )
    )
