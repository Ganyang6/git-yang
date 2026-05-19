"""
ONNX Runtime session manager for model lifecycle management.

Handles ONNX inference session creation, hot-swapping, and integrity checks.
Optimized for edge deployment on 2-core CPU with ~12MB model size.

Reference: spec_phase4_celery_ai_onnx.md Section 4.5-4.6
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)


class OnnxSessionManager:
    """Manages ONNX inference session lifecycle.

    Features:
    - Thread-safe inference (read-write lock pattern)
    - A/B hot-swap model loading
    - SHA-256 model integrity verification
    - CPU-optimized session options (2-core edge device)
    - Fallback-safe: returns None on inference failure (caller handles fallback)

    Usage:
        mgr = OnnxSessionManager("models/action_classifier_latest.onnx")
        if mgr.is_ready:
            result = mgr.predict(input_tensor)
    """

    def __init__(
        self,
        model_path: str,
        expected_checksum: Optional[str] = None,
        intra_threads: int = 2,
        inter_threads: int = 1,
    ):
        self._model_path = Path(model_path)
        self._expected_checksum = expected_checksum
        self._intra_threads = intra_threads
        self._inter_threads = inter_threads

        self._session = None
        self._metadata: Optional[Dict[str, Any]] = None
        self._lock = threading.RLock()
        self._inference_fail_count: int = 0
        self._INFERENCE_FAIL_THRESHOLD: int = 100

        if self._model_path.exists():
            logger.info(
                "ONNX model found at %s (size: %d bytes)",
                self._model_path, self._model_path.stat().st_size,
            )
        else:
            logger.info(
                "ONNX model not found at %s, will use rule-based classifier",
                self._model_path,
            )

    @property
    def is_ready(self) -> bool:
        """Whether the ONNX session is loaded and ready for inference."""
        return self._session is not None

    @property
    def model_path(self) -> str:
        return str(self._model_path)

    def ensure_loaded(self) -> bool:
        """Ensure the ONNX session is loaded.

        Returns True if session is ready, False if model file not found
        or integrity check failed.
        """
        with self._lock:
            if self._session is not None:
                return True
            return self._load_model(str(self._model_path))

    def _load_model(self, model_path: str) -> bool:
        """Load ONNX model from file path. Must be called under self._lock."""
        path = Path(model_path)
        if not path.exists():
            logger.warning("ONNX model file not found: %s", model_path)
            return False

        # Integrity check
        if self._expected_checksum:
            actual = self._compute_checksum(path)
            if actual != self._expected_checksum:
                logger.error(
                    "ONNX model integrity check FAILED for %s. "
                    "Expected: %s, Actual: %s",
                    model_path, self._expected_checksum[:16], actual[:16],
                )
                return False
            logger.info("ONNX model integrity check passed for %s", model_path)

        try:
            import onnxruntime as ort

            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = self._intra_threads
            sess_options.inter_op_num_threads = self._inter_threads
            sess_options.graph_optimization_level = (
                ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            )
            sess_options.enable_mem_pattern = False
            sess_options.log_severity_level = 3

            session = ort.InferenceSession(
                str(path),
                sess_options,
                providers=["CPUExecutionProvider"],
            )

            meta = self._extract_metadata(session)
            logger.info(
                "ONNX model loaded: %s | inputs=%s | outputs=%s | providers=%s",
                path.name,
                [m.name for m in session.get_inputs()],
                [m.name for m in session.get_outputs()],
                session.get_providers(),
            )

            self._session = session
            self._metadata = meta
            return True

        except ImportError:
            # Non-critical: ONNX is optional, falls back to rule-based classifier
            logger.warning(
                "onnxruntime not installed. Install with: pip install onnxruntime"
            )
            return False
        except Exception as exc:
            logger.error("Failed to load ONNX model %s: %s", model_path, exc)
            return False

    def predict(self, input_tensor: np.ndarray) -> Optional[np.ndarray]:
        """Execute inference on the loaded model.

        Returns output numpy array, or None if inference fails.
        Thread-safe.
        """
        if not self.ensure_loaded():
            return None

        with self._lock:
            if self._session is None:
                return None

            try:
                input_name = self._session.get_inputs()[0].name
                outputs = self._session.run(None, {input_name: input_tensor})
                self._inference_fail_count = 0  # Reset: inference recovered
                return outputs[0]
            except Exception as exc:
                self._inference_fail_count += 1
                logger.error(
                    "ONNX inference failed (failures=%d/%d): %s",
                    self._inference_fail_count, self._INFERENCE_FAIL_THRESHOLD, exc,
                )
                if self._inference_fail_count == self._INFERENCE_FAIL_THRESHOLD:
                    logger.error(
                        "ONNX inference failure threshold reached (%d). "
                        "Model may be corrupted or inputs incompatible.",
                        self._inference_fail_count,
                    )
                return None

    def predict_with_input_names(
        self, feed: Dict[str, np.ndarray]
    ) -> Optional[np.ndarray]:
        """Execute inference with named inputs (for multi-input models)."""
        if not self.ensure_loaded():
            return None

        with self._lock:
            if self._session is None:
                return None

            try:
                outputs = self._session.run(None, feed)
                self._inference_fail_count = 0  # Reset: inference recovered
                return outputs[0]
            except Exception as exc:
                self._inference_fail_count += 1
                logger.error(
                    "ONNX inference failed (failures=%d/%d): %s",
                    self._inference_fail_count, self._INFERENCE_FAIL_THRESHOLD, exc,
                )
                if self._inference_fail_count == self._INFERENCE_FAIL_THRESHOLD:
                    logger.error(
                        "ONNX inference failure threshold reached (%d). "
                        "Model may be corrupted or inputs incompatible.",
                        self._inference_fail_count,
                    )
                return None

    def get_model_metadata(self) -> Dict[str, Any]:
        """Get metadata about the loaded model.

        Returns dict with input_names, input_shapes, output_names, etc.
        Returns empty dict if model is not loaded.
        """
        if not self.ensure_loaded():
            return {}

        with self._lock:
            if self._session is None:
                return {}
            return dict(self._metadata) if self._metadata else {}

    def verify_integrity(self, expected_checksum: Optional[str] = None) -> bool:
        """Verify model file SHA-256 checksum.

        Args:
            expected_checksum: Expected SHA-256 hex digest. If None, uses
                the checksum provided at construction time.

        Returns:
            True if checksum matches (or no checksum to verify), False otherwise.
        """
        checksum = expected_checksum or self._expected_checksum
        if not checksum:
            return True
        if not self._model_path.exists():
            return False
        actual = self._compute_checksum(self._model_path)
        return actual == checksum

    def reload_model(self, new_model_path: str) -> bool:
        """Hot-swap the model to a new version (A/B pattern).

        Loads new model first, atomically swaps. If loading fails,
        the old model remains active.

        Returns True if hot-swap succeeded.
        """
        new_path = Path(new_model_path)
        if not new_path.exists():
            logger.error("New model file not found: %s", new_model_path)
            return False

        logger.info(
            "Hot-swapping ONNX model: %s -> %s",
            self._model_path, new_model_path,
        )

        with self._lock:
            old_session = self._session
            old_metadata = self._metadata

            if self._load_model(new_model_path):
                if old_session is not None:
                    try:
                        old_session.__exit__(None, None, None)
                    except Exception:
                        pass
                self._model_path = new_path
                logger.info("ONNX model hot-swap complete: %s", new_model_path)
                return True
            else:
                self._session = old_session
                self._metadata = old_metadata
                logger.error("ONNX model hot-swap failed, keeping old model")
                return False

    def close(self) -> None:
        """Release the ONNX session and free resources."""
        with self._lock:
            if self._session is not None:
                try:
                    self._session.__exit__(None, None, None)
                except Exception:
                    pass
                self._session = None
                self._metadata = None
                logger.info("ONNX session released")

    @staticmethod
    def _compute_checksum(path: Path) -> str:
        """Compute SHA-256 hex digest of a file."""
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(8192), b""):
                sha.update(block)
        return sha.hexdigest()

    @staticmethod
    def _extract_metadata(session: Any) -> Dict[str, Any]:
        """Extract model metadata from an ONNX session."""
        inputs = []
        for inp in session.get_inputs():
            inputs.append({
                "name": inp.name,
                "shape": list(inp.shape) if inp.shape else [],
                "type": str(inp.type),
            })

        outputs = []
        for out in session.get_outputs():
            outputs.append({
                "name": out.name,
                "shape": list(out.shape) if out.shape else [],
                "type": str(out.type),
            })

        model_info = {}
        if hasattr(session, "get_modelmeta"):
            meta = session.get_modelmeta()
            if meta and hasattr(meta, "custom_metadata_map"):
                model_info = dict(meta.custom_metadata_map) or {}

        return {
            "input_names": [i["name"] for i in inputs],
            "input_shapes": {i["name"]: i["shape"] for i in inputs},
            "output_names": [o["name"] for o in outputs],
            "output_shapes": {o["name"]: o["shape"] for o in outputs},
            "model_info": model_info,
        }
