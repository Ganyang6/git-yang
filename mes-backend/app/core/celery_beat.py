"""
Celery Beat periodic task schedule configuration.

Defines scheduled tasks for data aggregation, model health checks,
infrastructure heartbeat, and data cleanup.

Run as a separate process:
  celery -A app.core.celery_app beat --loglevel=info
"""

from __future__ import annotations

import os
from datetime import timedelta
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
    # Daily at 3 AM: clean up stale video files not referenced in task hash
    "cleanup-stale-videos": {
        "task": "cleanup_stale_videos",
        "schedule": crontab(hour=3, minute=0),
    },
    # Every 30 minutes: archive completed/failed/cancelled tasks from hash
    "cleanup-stale-completed-tasks": {
        "task": "cleanup_stale_completed_tasks",
        "schedule": crontab(minute="*/30"),
    },
    # Every 60 seconds: aggregate pending process segments into worktime records
    "aggregate-pending-segments": {
        "task": "aggregate_pending_segments",
        "schedule": timedelta(seconds=300),
    },
}

celery.conf.beat_schedule_filename = os.environ.get("BEAT_SCHEDULE_DB_PATH", "celerybeat-schedule.db")
celery.conf.timezone = "Asia/Shanghai"
celery.conf.enable_utc = True
