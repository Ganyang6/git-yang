"""ModelBackend Protocol — 动作分类后端抽象层

定义所有动作分类后端的协议接口，并提供内建实现：
- OnnxBackend: 包装现有的 OnnxActionClassifier
- RuleBackend: 包装规则引擎（兼容现有 ActionClassifier）

现有 OnnxActionClassifier 和 ActionClassifier 代码保持不变。
所有 classify 方法目前是同步的（无真正的异步 I/O）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class ModelBackend(Protocol):
    """所有动作分类后端的协议"""

    def classify(self, frames: list) -> Optional[dict]: ...


@dataclass
class ClassificationResult:
    """标准化的分类结果"""

    action: str
    confidence: float
    backend: str  # "onnx" | "rule"
    details: dict = field(default_factory=dict)


def _onnx_model_exists(model_path: str) -> bool:
    """Check if the ONNX model file exists at the given path.

    Resolves relative paths against the project root.
    """
    if os.path.isabs(model_path):
        return os.path.isfile(model_path)

    # Try relative to project root (mes-backend/)
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    full_path = os.path.join(project_root, model_path)
    return os.path.isfile(full_path)


class OnnxBackend:
    """包装现有的 OnnxActionClassifier

    如果 ONNX 模型不可用，classify 会优雅降级返回 None。
    """

    def __init__(self, model_path: str, threshold: float = 0.7):
        self._model_path = model_path
        self._threshold = threshold
        self._classifier = None
        self._available = False

        if _onnx_model_exists(model_path):
            try:
                from app.services.onnx_action_classifier import OnnxActionClassifier

                self._classifier = OnnxActionClassifier(
                    model_path=model_path,
                    confidence_threshold=threshold,
                )
                self._available = True
                logger.info("OnnxBackend initialized with model: %s", model_path)
            except Exception as e:
                logger.warning(
                    "OnnxBackend failed to load model %s: %s. Falling through.",
                    model_path,
                    e,
                )
                self._available = False
        else:
            logger.debug("ONNX model not found at %s", model_path)

    def classify(self, frames: list) -> Optional[ClassificationResult]:
        """Classify frames using ONNX model.

        Args:
            frames: List of frame data (pose landmarks).

        Returns:
            ClassificationResult if available and confident enough, else None.
        """
        if not self._available or self._classifier is None:
            return None

        try:
            result = self._classifier.classify(frames)
            if result is None:
                return None

            return ClassificationResult(
                action=result.label if hasattr(result, "label") else str(result),
                confidence=result.confidence
                if hasattr(result, "confidence")
                else 0.0,
                backend="onnx",
                details={
                    "model_path": self._model_path,
                    "threshold": self._threshold,
                },
            )
        except Exception as e:
            logger.warning("ONNX classify failed: %s", e)
            return None


class RuleBackend:
    """包装规则引擎（兼容现有 ActionClassifier）

    不需要 .onnx 文件即可工作，适合 fallback 场景。
    """

    def __init__(self):
        self._classifier = None
        self._available = False

        try:
            from app.services.action_classifier import ActionClassifier

            self._classifier = ActionClassifier()
            self._available = True
            logger.info("RuleBackend initialized with ActionClassifier")
        except ImportError:
            logger.warning(
                "ActionClassifier not available, using fallback classification"
            )
            self._available = False
        except Exception as e:
            logger.warning("RuleBackend init failed: %s. Using fallback.", e)
            self._available = False

    def classify(self, frames: list) -> ClassificationResult:
        """Classify frames using rule-based engine.

        Works even when ActionClassifier is unavailable by returning a
        best-effort result.

        Args:
            frames: List of frame data (pose landmarks).

        Returns:
            ClassificationResult always (fallback produces "idle" with low confidence).
        """
        if self._available and self._classifier is not None:
            try:
                if frames:
                    result = self._classifier.classify(frames)
                    if result is not None:
                        if hasattr(result, "label"):
                            return ClassificationResult(
                                action=result.label,
                                confidence=getattr(result, "confidence", 0.5),
                                backend="rule",
                                details={"source": "action_classifier"},
                            )
                        return ClassificationResult(
                            action=str(result),
                            confidence=0.5,
                            backend="rule",
                            details={"source": "action_classifier"},
                        )
            except Exception as e:
                logger.warning("Rule classify failed: %s. Using fallback.", e)

        # Fallback: return idle result
        return ClassificationResult(
            action="idle",
            confidence=0.3,
            backend="rule",
            details={
                "source": "fallback",
                "frames_count": len(frames) if frames else 0,
            },
        )


def create_backend(config) -> ModelBackend:
    """工厂函数：根据配置选择 backend

    Args:
        config: AppConfig-like object with onnx.enabled, onnx.model_path,
                onnx.confidence_threshold attributes.

    Returns:
        配置的 ModelBackend 实例。
    """
    if config.onnx.enabled and _onnx_model_exists(config.onnx.model_path):
        return OnnxBackend(
            config.onnx.model_path, config.onnx.confidence_threshold
        )
    return RuleBackend()
