"""Phase 3: Prometheus metrics definitions."""
from prometheus_client import Counter

tasks_created = Counter("mes_tasks_created_total", "Tasks created")
tasks_completed = Counter("mes_tasks_completed_total", "Tasks completed")
tasks_failed = Counter("mes_tasks_failed_total", "Tasks failed")
tasks_archived = Counter("mes_tasks_archived_cleanup_total", "Terminal-state tasks moved from active hash to archive")
