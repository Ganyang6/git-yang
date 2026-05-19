"""
Celery Beat periodic task schedule configuration.

Defines scheduled tasks for data aggregation, model health checks,
infrastructure heartbeat, and data cleanup.

Run as a separate process:
  celery -A app.core.celery_app beat --loglevel=info
"""

from __future__ import annotations

from pathlib import Path

from celery.schedules import crontab

from app.core.celery_app import celery

celery.conf.beat_schedule = {
    # Every hour: aggregate worktime metrics from InfluxDB
    "hourly-metrics-aggregation": {
        "task": "aggregate_hourly_metrics",
        "schedule": crontab(minute=0),
    },
    # Every 5 minutes: check ONNX model file integrity
    "model-health-check": {
        "task": "check_model_health",
        "schedule": crontab(minute="*/5"),
    },
    # Every minute: Redis/InfluxDB connection heartbeat
    "infrastructure-heartbeat": {
        "task": "infrastructure_heartbeat",
        "schedule": crontab(minute="*"),
    },
    # Daily at 2 AM: clean up expired data
    "daily-data-cleanup": {
        "task": "cleanup_expired_data",
        "schedule": crontab(hour=2, minute=0),
    },
}

celery.conf.beat_schedule_filename = "celerybeat-schedule.db"
celery.conf.timezone = "Asia/Shanghai"
celery.conf.enable_utc = True
