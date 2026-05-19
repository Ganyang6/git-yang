"""
Simple rule-based fallback engine for AI responses.

Provides fixed responses for common manufacturing-related queries
when DeepSeek API and cache are unavailable.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Keyword -> response mapping for common queries
_RULE_RESPONSES: Dict[str, str] = {
    "bottleneck": (
        "Based on current workstation load data, the bottleneck analysis "
        "requires access to real-time metrics. Please ensure the AI service "
        "is available for detailed analysis."
    ),
    "efficiency": (
        "Production efficiency analysis requires AI-powered computation. "
        "Current rule-based engine can only provide basic metrics. "
        "Please try again when the AI service is restored."
    ),
    "therblig": (
        "Therblig (motion element) analysis data is available through "
        "the worktime analysis API endpoints. The AI-powered interpretation "
        "service is currently unavailable."
    ),
    "balance": (
        "Line balance analysis requires AI computation. Please check "
        "the AI service health status and try again later."
    ),
    "anomaly": (
        "Anomaly detection and explanation requires AI-powered analysis. "
        "Basic anomaly flags are available through the metrics API."
    ),
    "worktime": (
        "Worktime analysis data is available through the API endpoints. "
        "AI-powered analysis and interpretation are currently unavailable."
    ),
}

_FALLBACK_RESPONSE = (
    "AI service is currently unavailable. Please try again later. "
    "Basic metrics and reports are still accessible through the dashboard."
)


class RuleEngine:
    """Keyword-based response generator for manufacturing queries.

    Used as the final fallback when both DeepSeek API and Redis cache
    are unavailable.
    """

    def generate_response(self, prompt: str, context: Optional[dict] = None) -> str:
        """Generate a rule-based response based on keyword matching.

        Args:
            prompt: User query text.
            context: Optional context dict (station_id, period, etc.).

        Returns:
            A predefined response string based on detected keywords.
        """
        prompt_lower = prompt.lower()

        for keyword, response in _RULE_RESPONSES.items():
            if keyword in prompt_lower:
                logger.info(
                    "Rule engine matched keyword '%s' for prompt: %.50s...",
                    keyword, prompt,
                )
                return response

        return _FALLBACK_RESPONSE
