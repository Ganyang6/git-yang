"""
Celery async task definitions for AI analysis.

Defines long-running AI tasks that are executed asynchronously
by the Celery worker (solo pool, Redis broker).

Core tasks:
  - analyze_worktime_task: Worktime analysis via AI gateway
  - analyze_line_balance_task: Line balance analysis
  - analyze_therblig_task: Therblig (motion element) ECRS optimization
  - generate_report_task: Generic report generation
  - send_notification_task: Fire-and-forget notification

Beat scheduled tasks:
  - aggregate_hourly_metrics: Hourly InfluxDB aggregation
  - check_model_health: ONNX model integrity check (every 5 min)
  - infrastructure_heartbeat: Redis/InfluxDB connectivity (every 1 min)
  - cleanup_expired_data: Daily data cleanup (2 AM)

Reference: spec_phase4_celery_ai_onnx.md Section 2.6
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.celery_app import celery

logger = logging.getLogger(__name__)

# Retryable exception types: network errors, API 5xx
_RETRYABLE_ERRORS = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def _is_retryable(exc: Exception) -> bool:
    """Check if an exception is retryable (transient network/API errors)."""
    if isinstance(exc, _RETRYABLE_ERRORS):
        return True
    exc_name = type(exc).__name__
    # httpx / asyncio network errors
    if any(kw in exc_name.lower() for kw in ("timeout", "connect", "connection")):
        return True
    # DeepSeek API 5xx errors
    if hasattr(exc, "status_code"):
        code = getattr(exc, "status_code", 0)
        if code >= 500:
            return True
    return False


# ── Gateway Factory ─────────────────────────────────────────────────

_gateway_cache: tuple | None = None


def _get_ai_gateway():
    """Lazy-load AIGateway singleton with config and optional Redis cache.

    Returns a cached (gateway, cache_store) tuple to avoid creating a new
    AIGateway and Redis connection on every task invocation (P1 #41).
    """
    global _gateway_cache
    if _gateway_cache is not None:
        return _gateway_cache

    from app.core.config import load_app_config
    from app.services.ai_gateway import AIGateway
    from app.services.cache_store import RedisCacheStore

    cfg = load_app_config()
    ai_cfg = cfg.ai

    # Try to create Redis-backed cache client
    cache_store = None
    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(
            cfg.redis.url, decode_responses=True, max_connections=2,
        )
        cache_store = RedisCacheStore(redis_client=redis_client)
    except Exception:
        logger.debug("Redis cache unavailable for Celery worker")

    gateway = AIGateway(
        api_key=ai_cfg.api_key,
        api_url=ai_cfg.api_url,
        model=ai_cfg.model,
        timeout=ai_cfg.timeout,
    )
    _gateway_cache = (gateway, cache_store)
    return _gateway_cache


# ── Prompt Builders ─────────────────────────────────────────────────

def _build_worktime_prompt(
    station_id: str, period: str, context_data: Optional[dict] = None,
) -> List[dict]:
    """Build prompt messages for worktime analysis."""
    system_msg = {
        "role": "system",
        "content": (
            "You are a manufacturing efficiency expert specializing in "
            "worktime analysis and therblig (motion element) optimization. "
            "Analyze the provided data and give actionable improvement "
            "suggestions. Use specific metrics and reference MOD method "
            "values when applicable."
        ),
    }
    user_content = (
        f"Station: {station_id}\n"
        f"Analysis period: {period}\n\n"
    )
    if context_data:
        user_content += f"Context data:\n```json\n{json.dumps(context_data, ensure_ascii=False, indent=2)}\n```\n\n"
    user_content += (
        "Please provide:\n"
        "1. Key findings from the worktime data\n"
        "2. Bottleneck identification\n"
        "3. Therblig optimization suggestions\n"
        "4. ECRS improvement recommendations"
    )
    return [system_msg, {"role": "user", "content": user_content}]


def _to_chat_messages(messages: List[dict]):
    """Convert plain dicts to ChatMessage dataclass for DeepSeek client."""
    from app.services.deepseek_client import ChatMessage
    return [ChatMessage(role=m["role"], content=m["content"]) for m in messages]


def _build_line_balance_prompt(line_id: str, context_data: Optional[dict] = None) -> List[dict]:
    """Build prompt messages for line balance analysis."""
    system_msg = {
        "role": "system",
        "content": (
            "You are a manufacturing line balance expert. Analyze the "
            "workstation load distribution and identify bottlenecks. "
            "Provide specific ECRS recommendations."
        ),
    }
    user_content = f"Line: {line_id}\n\n"
    if context_data:
        user_content += f"Station metrics:\n```json\n{json.dumps(context_data, ensure_ascii=False, indent=2)}\n```\n\n"
    user_content += (
        "Please provide:\n"
        "1. Line balance rate assessment\n"
        "2. Bottleneck workstation identification\n"
        "3. Workload redistribution suggestions\n"
        "4. Expected improvement after optimization"
    )
    return [system_msg, {"role": "user", "content": user_content}]


def _build_report_prompt(report_type: str, params: Optional[dict] = None) -> List[dict]:
    """Build prompt messages for generic report generation."""
    system_msg = {
        "role": "system",
        "content": (
            "You are a manufacturing data analyst. Generate a structured "
            "report based on the provided parameters and data."
        ),
    }
    user_content = f"Report type: {report_type}\n"
    if params:
        user_content += f"Parameters: {json.dumps(params, ensure_ascii=False)}\n\n"
    user_content += "Generate a comprehensive report with clear sections."
    return [system_msg, {"role": "user", "content": user_content}]


# ── Core AI Analysis Tasks ──────────────────────────────────────────

@celery.task(
    name="analyze_worktime",
    bind=True,
    soft_time_limit=45,
    hard_time_limit=60,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=30,
    retry_jitter=True,
)
def analyze_worktime_task(
    self,
    station_id: str,
    period: str,
    context_data: Optional[dict] = None,
) -> dict:
    """Analyze worktime data for a station using AI gateway.

    Args:
        station_id: Target station identifier.
        period: Analysis time period description.
        context_data: Dict with therblig stats, segment data, KPIs.

    Returns:
        Dict with: content, model_source, usage, duration_ms.
    """
    start = time.monotonic()
    logger.info("Starting worktime analysis: station=%s, period=%s", station_id, period)
    context_data = context_data or {}

    gateway, cache_store = _get_ai_gateway()
    if cache_store is not None:
        gateway.set_cache_store(cache_store)

    messages = _build_worktime_prompt(station_id, period, context_data)
    chat_messages = _to_chat_messages(messages)

    try:
        result = asyncio.run(asyncio.wait_for(gateway.analyze(
            prompt="",  # messages override prompt
            messages=chat_messages,
            context={"analysis_type": "worktime", "station_id": station_id},
        ), timeout=40))

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "Worktime analysis OK: station=%s, source=%s, %dms",
            station_id, result.get("model_source"), duration_ms,
        )
        return {
            "content": result.get("content", ""),
            "model_source": result.get("model_source", "unknown"),
            "usage": result.get("usage", {}),
            "duration_ms": duration_ms,
            "station_id": station_id,
            "period": period,
        }

    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("Worktime analysis FAILED: station=%s, %dms: %s", station_id, duration_ms, exc)
        if _is_retryable(exc):
            logger.info("Retrying worktime analysis: retryable error %s", type(exc).__name__)
            raise self.retry(exc=exc)
        return {
            "content": "Analysis failed. Please try again later or contact support.",
            "model_source": "error",
            "usage": {},
            "duration_ms": duration_ms,
            "station_id": station_id,
            "period": period,
            "error": "internal_error",
        }


@celery.task(
    name="analyze_line_balance",
    bind=True,
    soft_time_limit=45,
    hard_time_limit=60,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=30,
    retry_jitter=True,
)
def analyze_line_balance_task(
    self,
    line_id: str,
    context_data: Optional[dict] = None,
) -> dict:
    """Analyze production line balance using AI gateway."""
    start = time.monotonic()
    logger.info("Starting line balance analysis: line=%s", line_id)
    context_data = context_data or {}

    gateway, cache_store = _get_ai_gateway()
    if cache_store is not None:
        gateway.set_cache_store(cache_store)

    messages = _build_line_balance_prompt(line_id, context_data)
    chat_messages = _to_chat_messages(messages)

    try:
        result = asyncio.run(asyncio.wait_for(gateway.analyze(
            prompt="",
            messages=chat_messages,
            context={"analysis_type": "line_balance", "line_id": line_id},
        ), timeout=40))

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "Line balance analysis OK: line=%s, source=%s, %dms",
            line_id, result.get("model_source"), duration_ms,
        )
        return {
            "content": result.get("content", ""),
            "model_source": result.get("model_source", "unknown"),
            "usage": result.get("usage", {}),
            "duration_ms": duration_ms,
            "line_id": line_id,
        }

    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("Line balance analysis FAILED: line=%s, %dms: %s", line_id, duration_ms, exc)
        if _is_retryable(exc):
            logger.info("Retrying line balance analysis: retryable error %s", type(exc).__name__)
            raise self.retry(exc=exc)
        return {
            "content": "Line balance analysis failed. Please try again later.",
            "model_source": "error",
            "usage": {},
            "duration_ms": duration_ms,
            "line_id": line_id,
            "error": "internal_error",
        }


@celery.task(
    name="analyze_therblig",
    bind=True,
    soft_time_limit=45,
    hard_time_limit=60,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=30,
    retry_jitter=True,
)
def analyze_therblig_task(
    self,
    station_id: str,
    therblig_stats: Optional[dict] = None,
    mod_data: Optional[dict] = None,
    context_data: Optional[dict] = None,
) -> dict:
    """Analyze therblig (motion element) optimization using ECRS framework.

    Delegates to AIGateway.analyze_therblig() which builds a specialized
    prompt with therblig stats, MOD comparison data, and calls DeepSeek
    with the three-level degradation chain.

    Args:
        station_id: Target workstation identifier.
        therblig_stats: Dict mapping therblig names to stats dicts
            with keys: symbol, count, total_mod, is_waste.
        mod_data: Dict with MOD comparison data:
            actual_mod, target_mod, savings_mod, savings_pct.
        context_data: Optional extra context forwarded from API.

    Returns:
        Dict with: content, model_source, usage, duration_ms.
    """
    start = time.monotonic()
    logger.info("Starting therblig optimization: station=%s", station_id)

    gateway, cache_store = _get_ai_gateway()
    if cache_store is not None:
        gateway.set_cache_store(cache_store)

    try:
        result = asyncio.run(asyncio.wait_for(gateway.analyze_therblig(
            station_id=station_id,
            therblig_stats=therblig_stats,
            mod_data=mod_data,
        ), timeout=40))

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "Therblig optimization OK: station=%s, source=%s, %dms",
            station_id, result.get("model_source"), duration_ms,
        )
        return {
            "content": result.get("content", ""),
            "model_source": result.get("model_source", "unknown"),
            "usage": result.get("usage", {}),
            "duration_ms": duration_ms,
            "station_id": station_id,
        }

    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("Therblig optimization FAILED: station=%s, %dms: %s", station_id, duration_ms, exc)
        if _is_retryable(exc):
            logger.info("Retrying therblig optimization: retryable error %s", type(exc).__name__)
            raise self.retry(exc=exc)
        return {
            "content": "Therblig analysis failed. Please try again later.",
            "model_source": "error",
            "usage": {},
            "duration_ms": duration_ms,
            "station_id": station_id,
            "error": "internal_error",
        }


@celery.task(
    name="generate_report",
    bind=True,
    soft_time_limit=45,
    hard_time_limit=60,
    max_retries=2,
    retry_backoff=True,
)
def generate_report_task(
    self,
    report_type: str,
    params: Optional[dict] = None,
) -> dict:
    """Generate a report using AI gateway."""
    start = time.monotonic()
    logger.info("Starting report generation: type=%s", report_type)
    params = params or {}

    gateway, cache_store = _get_ai_gateway()
    if cache_store is not None:
        gateway.set_cache_store(cache_store)

    messages = _build_report_prompt(report_type, params)
    chat_messages = _to_chat_messages(messages)

    try:
        result = asyncio.run(asyncio.wait_for(gateway.analyze(
            prompt="",
            messages=chat_messages,
            context={"analysis_type": report_type},
        ), timeout=40))

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("Report generation OK: type=%s, source=%s", report_type, result.get("model_source"))
        return {
            "content": result.get("content", ""),
            "model_source": result.get("model_source", "unknown"),
            "usage": result.get("usage", {}),
            "duration_ms": duration_ms,
            "report_type": report_type,
        }

    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("Report generation FAILED: type=%s: %s", report_type, exc)
        if _is_retryable(exc):
            logger.info("Retrying report generation: retryable error %s", type(exc).__name__)
            raise self.retry(exc=exc)
        return {
            "content": "Report generation failed. Please try again later.",
            "model_source": "error",
            "usage": {},
            "duration_ms": duration_ms,
            "report_type": report_type,
            "error": "internal_error",
        }


@celery.task(name="send_notification", ignore_result=True)
def send_notification_task(
    message: str,
    recipients: Optional[list] = None,
    notification_type: str = "info",
) -> None:
    """Fire-and-forget notification task.

    Phase 4: log only. Phase 5+: integrate with WebSocket/email/SMS.
    """
    recipients = recipients or []
    logger.info(
        "Notification [%s] to %s: %s",
        notification_type, recipients[:3], message[:100],
    )


# ── Beat Scheduled Maintenance Tasks ────────────────────────────────

@celery.task(name="aggregate_hourly_metrics", ignore_result=True)
def aggregate_hourly_metrics() -> None:
    """Hourly: aggregate worktime metrics from InfluxDB.

    Queries per-station average HUR, total worktime, and therblig
    distribution over the past hour. Writes aggregated summaries to
    the system_health measurement for downstream dashboard consumption.
    """
    logger.info("Starting hourly metrics aggregation")
    try:
        from app.core.config import load_app_config
        from app.core.influxdb_client import InfluxDBClient as IdbClient

        cfg = load_app_config()
        client = IdbClient(cfg.influxdb)
        if not client.initialize():
            logger.warning("Hourly aggregation: InfluxDB not available")
            return

        try:
            # Build a Flux query that aggregates HUR across all stations
            # for the past hour, grouped by station_id.
            # We use the raw _query_api since query_aggregated_metrics
            # requires a specific station_id filter.
            query = f'''
            from(bucket: "{client.config.bucket}")
              |> range(start: -1h)
              |> filter(fn: (r) => r._measurement == "realtime_metrics")
              |> filter(fn: (r) => r._field == "hur")
              |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
              |> group(columns: ["station_id"])
              |> mean()
            '''
            tables = client._query_api.query(query, org=client.config.org)
            agg_results = client._tables_to_dicts(tables)

            if not agg_results:
                logger.info("Hourly aggregation: no data in the past hour")
                client.close()
                return

            # Each result record represents the mean HUR for one station
            for record in agg_results:
                sid = record.get("station_id", "unknown")
                avg_hur = float(record.get("_value", 0))
                client.write_system_health(
                    service=f"hourly_agg_{sid}",
                    request_latency_ms=round(avg_hur * 100, 1),
                    avg_hur=round(avg_hur, 4),
                )
            logger.info(
                "Hourly aggregation: wrote summaries for %d stations",
                len(agg_results),
            )
        except Exception as e:
            logger.error("Hourly aggregation query/write failed: %s", e)
        finally:
            client.close()
    except Exception as e:
        logger.error("Hourly metrics aggregation failed: %s", e)


@celery.task(name="check_model_health", ignore_result=True)
def check_model_health() -> None:
    """Every 5 min: check ONNX model file integrity."""
    from app.core.config import load_app_config
    import os

    cfg = load_app_config()
    model_path = cfg.onnx.model_path

    if not os.path.exists(model_path):
        logger.debug("Model health: no model at %s", model_path)
        return

    try:
        from app.services.onnx_session_manager import OnnxSessionManager

        if cfg.onnx.sha256_checksum:
            mgr = OnnxSessionManager(model_path)
            if not mgr.verify_integrity(cfg.onnx.sha256_checksum):
                logger.warning("Model integrity check FAILED: %s", model_path)
            else:
                logger.debug("Model integrity OK: %s", model_path)
            mgr.close()
    except Exception as e:
        logger.error("Model health check error: %s", e)


@celery.task(name="infrastructure_heartbeat", ignore_result=True)
def infrastructure_heartbeat() -> None:
    """Every minute: check Redis and InfluxDB connectivity."""
    import redis as sync_redis
    from app.core.config import load_app_config

    cfg = load_app_config()

    # Redis
    try:
        r = sync_redis.from_url(cfg.redis.url, socket_connect_timeout=2)
        r.ping()
        r.close()
        logger.debug("Heartbeat: Redis OK")
    except Exception as e:
        logger.warning("Heartbeat: Redis FAIL - %s", e)

    # InfluxDB
    try:
        from influxdb_client import InfluxDBClient as InfluxClient
        influx = InfluxClient(url=cfg.influxdb.url, token=cfg.influxdb.token, org=cfg.influxdb.org, timeout=2000)
        influx.health()
        influx.close()
        logger.debug("Heartbeat: InfluxDB OK")
    except Exception as e:
        logger.warning("Heartbeat: InfluxDB FAIL - %s", e)


@celery.task(name="cleanup_expired_data", ignore_result=True)
def cleanup_expired_data() -> None:
    """Daily at 2 AM: clean up cache entries with no remaining TTL.

    Redis TTL handles actual expiry automatically. This task only
    removes keys that have no TTL set (orphaned entries).
    """
    logger.info("Starting daily data cleanup")
    try:
        import redis as sync_redis
        from app.core.config import load_app_config

        cfg = load_app_config()
        r = sync_redis.from_url(cfg.redis.url, socket_connect_timeout=2)

        deleted = 0
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match="ai:cache:*", count=100)
            if keys:
                # Only delete keys with no TTL (TTL == -1 means no expiry set)
                orphaned = [
                    k for k in keys
                    if r.ttl(k) == -1
                ]
                if orphaned:
                    deleted += r.delete(*orphaned)
            if cursor == 0:
                break

        logger.info("Daily cleanup: removed %d orphaned cache entries (no TTL)", deleted)
        r.close()
    except Exception as e:
        logger.error("Daily data cleanup failed: %s", e)
