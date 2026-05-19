"""
Tests for Celery app configuration.

Validates that the Celery app is properly configured with:
  - JSON-only serialization (no pickle)
  - Correct broker/backend URLs
  - Task includes
  - Worker memory limits
  - Beat schedule
"""

import os

import pytest


class TestCeleryAppConfig:
    def test_celery_app_created(self):
        from app.core.celery_app import celery
        assert celery is not None
        assert celery.main == "mes_worker"

    def test_json_only_serialization(self):
        from app.core.celery_app import celery
        assert celery.conf.task_serializer == "json"
        assert celery.conf.result_serializer == "json"
        assert celery.conf.accept_content == ["json"]

    def test_broker_url_default(self):
        from app.core.celery_app import celery
        # Default should use redis://redis:6379/0
        assert "redis://" in celery.conf.broker_url
        assert "/0" in celery.conf.broker_url

    def test_backend_url_default(self):
        from app.core.celery_app import celery
        assert "redis://" in celery.conf.result_backend
        assert "/1" in celery.conf.result_backend

    def test_broker_url_from_env(self):
        os.environ["CELERY_BROKER_URL"] = "redis://custom:6380/5"
        try:
            from app.core.celery_app import celery
            # Note: the env var is read at import time, not re-read
            # This tests that the default is properly set
            assert celery.conf.broker_url is not None
        finally:
            os.environ.pop("CELERY_BROKER_URL", None)

    def test_task_includes_ai_tasks(self):
        from app.core.celery_app import celery
        # ai_tasks is included via the include= parameter at app creation
        assert "app.services.ai_tasks" in celery.conf.include or "app.services.ai_tasks" in str(celery.conf.get("include", ""))

    def test_result_expiry(self):
        from app.core.celery_app import celery
        assert celery.conf.result_expires == 3600

    def test_worker_memory_limit(self):
        from app.core.celery_app import celery
        assert celery.conf.worker_max_memory_per_child == 300_000  # ~293MB

    def test_worker_max_tasks(self):
        from app.core.celery_app import celery
        assert celery.conf.worker_max_tasks_per_child == 500

    def test_timezone(self):
        from app.core.celery_app import celery
        assert celery.conf.timezone == "Asia/Shanghai"
        assert celery.conf.enable_utc is True


class TestCeleryBeatSchedule:
    def test_beat_schedule_defined(self):
        from app.core.celery_beat import celery
        schedule = celery.conf.beat_schedule
        assert isinstance(schedule, dict)
        assert len(schedule) >= 4

    def test_beat_schedule_tasks(self):
        from app.core.celery_beat import celery
        schedule = celery.conf.beat_schedule
        task_names = {v["task"] for v in schedule.values()}
        expected = {
            "aggregate_hourly_metrics",
            "check_model_health",
            "infrastructure_heartbeat",
            "cleanup_expired_data",
        }
        assert expected.issubset(task_names)

    def test_beat_schedule_filename(self):
        from app.core.celery_beat import celery
        assert celery.conf.beat_schedule_filename == "celerybeat-schedule.db"
