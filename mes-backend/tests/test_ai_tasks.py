"""
Tests for Celery AI task definitions.

Mocks the AI gateway and config to test task:
  - Function signatures and parameter handling
  - Prompt building logic
  - Return value structure
  - Error handling and fallback behavior
  - Notification task (fire-and-forget)
  - Beat maintenance task function definitions
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Prompt Builders (pure functions, no mocks needed)
# ---------------------------------------------------------------------------


class TestPromptBuilders:
    def test_build_worktime_prompt_structure(self):
        from app.services.ai_tasks import _build_worktime_prompt
        msgs = _build_worktime_prompt("STA-01", "2026-03", context_data={"utilization": 85})
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert "STA-01" in msgs[1]["content"]
        assert "2026-03" in msgs[1]["content"]
        assert "utilization" in msgs[1]["content"]

    def test_build_worktime_prompt_without_context(self):
        from app.services.ai_tasks import _build_worktime_prompt
        msgs = _build_worktime_prompt("STA-01", "2026-03")
        assert "Context data" not in msgs[1]["content"]

    def test_build_line_balance_prompt(self):
        from app.services.ai_tasks import _build_line_balance_prompt
        msgs = _build_line_balance_prompt("L01", {"station_count": 5})
        assert len(msgs) == 2
        assert "L01" in msgs[1]["content"]
        assert "station_count" in msgs[1]["content"]

    def test_build_report_prompt(self):
        from app.services.ai_tasks import _build_report_prompt
        msgs = _build_report_prompt("monthly", {"period": "2026-03"})
        assert "monthly" in msgs[1]["content"]
        assert "period" in msgs[1]["content"]

    def test_to_chat_messages(self):
        from app.services.ai_tasks import _to_chat_messages
        from app.services.deepseek_client import ChatMessage

        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        result = _to_chat_messages(msgs)
        assert len(result) == 2
        assert isinstance(result[0], ChatMessage)
        assert result[0].role == "system"
        assert result[1].content == "Hello"


# ---------------------------------------------------------------------------
# Core AI Tasks (mock gateway)
# ---------------------------------------------------------------------------


class TestAnalyzeWorktimeTask:
    @patch("app.services.ai_tasks._get_ai_gateway")
    def test_returns_result_on_success(self, mock_get_gateway):
        from app.services.ai_tasks import analyze_worktime_task

        mock_gw = MagicMock()
        mock_gw.analyze = AsyncMock(return_value={
            "content": "Analysis result",
            "model_source": "deepseek",
            "usage": {"input_tokens": 10, "output_tokens": 20},
        })
        mock_cache = MagicMock()
        mock_get_gateway.return_value = (mock_gw, mock_cache)

        result = analyze_worktime_task("STA-01", "2026-03")

        assert result["content"] == "Analysis result"
        assert result["model_source"] == "deepseek"
        assert result["station_id"] == "STA-01"
        assert result["period"] == "2026-03"
        assert "duration_ms" in result

    @patch("app.services.ai_tasks._get_ai_gateway")
    def test_returns_error_on_failure(self, mock_get_gateway):
        from app.services.ai_tasks import analyze_worktime_task

        mock_gw = MagicMock()
        mock_gw.analyze = AsyncMock(side_effect=Exception("API down"))
        mock_cache = MagicMock()
        mock_get_gateway.return_value = (mock_gw, mock_cache)

        result = analyze_worktime_task("STA-01", "2026-03")

        assert result["model_source"] == "error"
        assert "error" in result
        assert result["station_id"] == "STA-01"

    @patch("app.services.ai_tasks._get_ai_gateway")
    def test_injects_cache_store(self, mock_get_gateway):
        from app.services.ai_tasks import analyze_worktime_task

        mock_gw = MagicMock()
        mock_gw.analyze = AsyncMock(return_value={
            "content": "ok",
            "model_source": "rule_engine",
        })
        mock_gw.set_cache_store = MagicMock()
        mock_cache = MagicMock()
        mock_get_gateway.return_value = (mock_gw, mock_cache)

        analyze_worktime_task("STA-01", "2026-03")
        mock_gw.set_cache_store.assert_called_once_with(mock_cache)


class TestAnalyzeLineBalanceTask:
    @patch("app.services.ai_tasks._get_ai_gateway")
    def test_returns_result_on_success(self, mock_get_gateway):
        from app.services.ai_tasks import analyze_line_balance_task

        mock_gw = MagicMock()
        mock_gw.analyze = AsyncMock(return_value={
            "content": "Balance result",
            "model_source": "deepseek",
        })
        mock_cache = MagicMock()
        mock_get_gateway.return_value = (mock_gw, mock_cache)

        result = analyze_line_balance_task("L01")

        assert result["content"] == "Balance result"
        assert result["line_id"] == "L01"
        assert "duration_ms" in result


class TestGenerateReportTask:
    @patch("app.services.ai_tasks._get_ai_gateway")
    def test_returns_result_on_success(self, mock_get_gateway):
        from app.services.ai_tasks import generate_report_task

        mock_gw = MagicMock()
        mock_gw.analyze = AsyncMock(return_value={
            "content": "Report text",
            "model_source": "deepseek",
        })
        mock_cache = MagicMock()
        mock_get_gateway.return_value = (mock_gw, mock_cache)

        result = generate_report_task("monthly", {"period": "2026-03"})

        assert result["content"] == "Report text"
        assert result["report_type"] == "monthly"


class TestSendNotificationTask:
    def test_notification_task_runs_without_error(self):
        from app.services.ai_tasks import send_notification_task

        # Fire-and-forget, should not raise
        result = send_notification_task("Test message", recipients=["user1"])
        assert result is None


# ---------------------------------------------------------------------------
# Beat Maintenance Tasks
# ---------------------------------------------------------------------------


class TestBeatMaintenanceTasks:
    def test_aggregate_hourly_metrics_handles_no_influxdb(self):
        from app.services.ai_tasks import aggregate_hourly_metrics

        # Should not raise when InfluxDB is unavailable
        result = aggregate_hourly_metrics()
        assert result is None

    def test_check_model_health_handles_missing_model(self):
        from app.services.ai_tasks import check_model_health

        # Should not raise when model file is missing
        result = check_model_health()
        assert result is None

    def test_cleanup_expired_data_handles_no_redis(self):
        from app.services.ai_tasks import cleanup_expired_data

        # Should not raise when Redis is unavailable
        result = cleanup_expired_data()
        assert result is None
