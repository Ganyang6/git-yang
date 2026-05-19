"""Tests for AI Therblig Optimization Engine (T5-04).

Covers:
  - TherbligOptimizationPrompt template
  - AIGateway.analyze_therblig() method
"""

from __future__ import annotations

import pytest
from typing import Any, Dict


class TestTherbligOptimizationPrompt:
    """TherbligOptimizationPrompt template tests."""

    def test_template_registered(self):
        from app.services.prompt_templates import get_template, TEMPLATES
        assert "therblig_optimization" in TEMPLATES
        tmpl = get_template("therblig_optimization")
        assert tmpl is not None

    def test_build_with_therblig_stats(self):
        from app.services.prompt_templates import TherbligOptimizationPrompt

        tmpl = TherbligOptimizationPrompt()
        data = {
            "station_id": "ws_01",
            "period": "today",
            "therblig_stats": {
                "reach": {"symbol": "R", "count": 20, "total_mod": 60.0, "is_waste": False},
                "grasp": {"symbol": "G", "count": 15, "total_mod": 15.0, "is_waste": False},
                "unavoidable_delay": {"symbol": "UD", "count": 10, "total_mod": 0.0, "is_waste": True},
            },
        }

        result = tmpl.build(data)
        assert isinstance(result, str)
        assert len(result) > 100
        assert "ECRS" in result
        assert "ws_01" in result
        assert "reach" in result
        assert "unavoidable_delay" in result
        assert "MOD" in result
        assert "Eliminate" in result

    def test_build_with_mod_comparison(self):
        from app.services.prompt_templates import TherbligOptimizationPrompt

        tmpl = TherbligOptimizationPrompt()
        data = {
            "station_id": "ws_02",
            "therblig_stats": {},
            "mod_comparison": {
                "actual_mod": 120.0,
                "target_mod": 95.0,
                "savings_mod": 25.0,
                "savings_pct": 0.208,
            },
        }

        result = tmpl.build(data)
        assert "Standard MOD" in result or "MOD Standard" in result
        assert "25.0" in result

    def test_build_with_action_summary(self):
        from app.services.prompt_templates import TherbligOptimizationPrompt

        tmpl = TherbligOptimizationPrompt()
        data = {
            "station_id": "ws_03",
            "action_summary": {
                "reach": {"count": 20, "avg_duration_ms": 500},
                "assemble": {"count": 10, "avg_duration_ms": 2000},
                "wait": {"count": 5, "avg_duration_ms": 3000},
            },
        }

        result = tmpl.build(data)
        assert "Action Classification" in result
        assert "reach" in result

    def test_build_empty_data(self):
        from app.services.prompt_templates import TherbligOptimizationPrompt

        tmpl = TherbligOptimizationPrompt()
        result = tmpl.build({})
        assert "ECRS" in result
        assert "MOD" in result

    def test_build_output_structure(self):
        from app.services.prompt_templates import TherbligOptimizationPrompt

        tmpl = TherbligOptimizationPrompt()
        result = tmpl.build({"station_id": "ws_01"})

        # Check all required output sections are mentioned
        assert "ECRS" in result
        assert "Improvement" in result or "improvement" in result
        assert "Before" in result or "before" in result
        assert "Priority" in result or "priority" in result

    def test_truncation(self):
        from app.services.prompt_templates import TherbligOptimizationPrompt

        tmpl = TherbligOptimizationPrompt()
        # Very long data should be truncated
        long_stats = {}
        for i in range(100):
            long_stats[f"therblig_{i}"] = {
                "symbol": f"T{i}",
                "count": 1000,
                "total_mod": 500.0,
                "is_waste": i % 3 == 0,
            }
        data = {"station_id": "ws_01", "therblig_stats": long_stats}
        result_no_trunc = tmpl.build(data, max_length=100000)
        result_trunc = tmpl.build(data, max_length=500)
        # Truncated version should be shorter
        assert len(result_trunc) < len(result_no_trunc)
        assert "truncated" in result_trunc


class TestAnalyzeTherblig:
    """AIGateway.analyze_therblig() method tests."""

    @pytest.mark.asyncio
    async def test_returns_rule_engine_response_when_no_deepseek(self):
        from app.services.ai_gateway import AIGateway

        gateway = AIGateway()
        result = await gateway.analyze_therblig(
            station_id="ws_01",
            therblig_stats={
                "reach": {"symbol": "R", "count": 20, "total_mod": 60.0, "is_waste": False},
            },
        )

        assert "content" in result
        assert result["level"] == "rule_engine"
        assert result["content"] is not None
        assert len(result["content"]) > 0

    @pytest.mark.asyncio
    async def test_passes_station_id_to_context(self):
        from app.services.ai_gateway import AIGateway
        from unittest.mock import patch, AsyncMock

        gateway = AIGateway()
        # Mock analyze to capture context
        captured_context = None

        async def mock_analyze(*, prompt, context=None, messages=None, stream=False):
            nonlocal captured_context
            captured_context = context
            return {"content": "test", "level": "mock", "model_source": "mock", "streamed": False, "generator": None}

        gateway.analyze = mock_analyze
        await gateway.analyze_therblig(station_id="ws_99", therblig_stats={})

        assert captured_context is not None
        assert captured_context.get("station_id") == "ws_99"
        assert captured_context.get("analysis_type") == "therblig_optimization"

    @pytest.mark.asyncio
    async def test_handles_empty_stats(self):
        from app.services.ai_gateway import AIGateway

        gateway = AIGateway()
        result = await gateway.analyze_therblig(station_id="ws_01")

        assert "content" in result
        assert result["level"] in ("rule_engine", "cache", "deepseek")
