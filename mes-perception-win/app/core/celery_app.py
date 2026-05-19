"""
Celery application configuration for MES async task processing.

Uses Redis as broker (db0) and result backend (db1).
Strict JSON serialization only (pickle prohibited for security).
Configured for edge deployment with solo pool and memory limits.
"""

from __future__ import annotations

import os

from celery import Celery

celery = Celery(
    "mes_worker",
    broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1"),
    include=[
        "app.services.ai_tasks",
        "app.services.worktime_aggregator",
    ],
)

celery.conf.update(
    # Serialization (security first - pickle is strictly rejected)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Result expiry: auto-cleanup after 1h to prevent Redis memory bloat
    result_expires=3600,
    # Memory protection
    worker_max_tasks_per_child=500,
    worker_max_memory_per_child=300_000,  # KB (~293MB)
    worker_eta_task_limit=1000,
    # Timezone
    timezone="Asia/Shanghai",
    enable_utc=True,
)
