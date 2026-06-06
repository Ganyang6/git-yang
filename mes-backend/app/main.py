"""
FastAPI application entry point.

Start with: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

API docs (auto-generated):
  - Swagger:  http://localhost:8000/docs
  - ReDoc:    http://localhost:8000/redoc
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from app.core.errors import AppError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import load_app_config
from app.models.database import init_db
from app.api.v1.ingest import router as ingest_router
from app.api.v1.worktime import router as worktime_router
from app.api.v1.ai import router as ai_router
from app.api.v1.auth import router as auth_router
from app.api.v1.orders import router as orders_router
from app.api.v1.customers import router as customers_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.equipment import router as equipment_router
from app.api.v1.reports import router as reports_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.enums import router as enums_router
from app.api.v1.line_balance import router as line_balance_router
from app.api.websocket import router as websocket_router
from app.api.sse import router as sse_router
from app.api.sse_chat import router as sse_chat_router
from app.api.v1.anomaly import router as anomaly_router
from app.api.v1.video import router as video_router
from app.api.v1.quality import router as quality_router

from app.core.metrics import tasks_created, tasks_completed, tasks_failed, tasks_archived
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

logger = logging.getLogger("mes_backend")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ── Lifespan: init infrastructure on startup, graceful shutdown ───────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks.

    Startup sequence:
    1. SQLite database (required)
    2. Redis (optional - graceful degradation)
    3. InfluxDB (optional - graceful degradation)
    4. Stream consumers (optional - requires Redis)
    5. ONNX Session Manager (optional - requires model file)
    6. AI Gateway with cache (optional - requires Redis)

    All optional services log a warning but do not prevent startup.
    """
    cfg = load_app_config()

    # 1. Initialize database (creates tables if not exist)
    db_url = os.environ.get("MES_DB_URL", cfg.database.url)
    if not db_url:
        raise RuntimeError(
            "Database URL is not configured. Set MES_DB_URL environment "
            "variable or app.database.url in config.yaml."
        )
    logger.info("Initializing database: %s", db_url)
    init_db(db_url=db_url, echo=cfg.database.echo)
    logger.info("Database ready")

    # 2. Initialize Redis (optional)
    redis_client = None
    try:
        from app.core.redis_client import RedisClient

        redis_cfg = cfg.redis
        redis_client = RedisClient(redis_cfg)
        # In test environment, override pool creation with shorter timeouts
        is_test = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        if is_test:
            import redis.asyncio as _aioredis
            redis_client._pool = _aioredis.from_url(
                redis_cfg.url,
                decode_responses=True,
                max_connections=2,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        else:
            await redis_client.connect()
        try:
            await redis_client._pool.ping()
            logger.info("Redis connected")
        except Exception:
            redis_client = None
            logger.warning("Redis not available (non-critical)")
    except Exception as e:
        logger.warning("Redis not available (non-critical): %s", e)

    # 3. Initialize InfluxDB (optional)
    influxdb_client = None
    try:
        from app.core.influxdb_client import InfluxDBClient as IdbClient

        idb_cfg = cfg.influxdb
        # In test environment, use 1s timeout instead of 5s default
        is_test = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        if is_test:
            influxdb_client = IdbClient(idb_cfg)
            try:
                from influxdb_client import InfluxDBClient as InfluxClient
                influxdb_client._client = InfluxClient(
                    url=idb_cfg.url,
                    token=idb_cfg.token,
                    org=idb_cfg.org,
                    timeout=1000,
                )
                influxdb_client._client.health()
                influxdb_client._query_api = influxdb_client._client.query_api()
                influxdb_client._write_api = influxdb_client._client.write_api(
                    write_precision=idb_cfg.write_precision,
                )
                logger.info("InfluxDB initialized (test mode)")
            except Exception:
                influxdb_client = None
                logger.warning("InfluxDB initialization failed (non-critical)")
        else:
            influxdb_client = IdbClient(idb_cfg)
            if influxdb_client.initialize():
                logger.info("InfluxDB initialized: %s", cfg.influxdb.url)
            else:
                influxdb_client = None
                logger.warning("InfluxDB initialization failed (non-critical)")
    except Exception as e:
        logger.warning("InfluxDB not available (non-critical): %s", e)

    # 4. Ensure Redis consumer groups exist before starting consumers
    if redis_client is not None:
        try:
            await redis_client.ensure_consumer_groups()
            logger.info("Redis consumer groups ensured")
        except Exception as e:
            logger.warning("Failed to ensure consumer groups (non-critical): %s", e)

    # 5. Start stream consumers (optional - requires Redis)
    metric_aggregator = None
    if redis_client is not None:
        try:
            from app.services.stream_consumers import MetricAggregator

            metric_aggregator = MetricAggregator(redis_client, influxdb_client)
            await metric_aggregator.start()
            logger.info("Stream consumers started")
        except Exception as e:
            logger.warning("Failed to start stream consumers (non-critical): %s", e)

    # Store references on app state for access from routes
    app.state.redis_client = redis_client
    app.state.influxdb_client = influxdb_client
    app.state.metric_aggregator = metric_aggregator

    # Initialize VideoTaskManager with shared Redis client
    try:
        from app.services.video_task_manager import get_task_manager, set_main_loop
        set_main_loop(asyncio.get_running_loop())
        get_task_manager(use_redis=True, redis_client=redis_client)
        logger.info("VideoTaskManager initialized with shared Redis client")
    except Exception as e:
        logger.warning("VideoTaskManager Redis init failed (non-critical): %s", e)

    # 5. Initialize ONNX Session Manager (optional - requires model file)
    onnx_session_mgr = None
    try:
        from app.services.onnx_session_manager import OnnxSessionManager

        onnx_cfg = cfg.onnx
        onnx_session_mgr = OnnxSessionManager(
            model_path=onnx_cfg.model_path,
            expected_checksum=onnx_cfg.sha256_checksum,
        )
        if onnx_session_mgr.ensure_loaded():
            logger.info("ONNX Session Manager initialized: %s", onnx_cfg.model_path)
        else:
            onnx_session_mgr = None
            logger.info("ONNX model not available, using rule-based classifier")
    except Exception as e:
        logger.warning("ONNX initialization failed (non-critical): %s", e)

    app.state.onnx_session_mgr = onnx_session_mgr

    # 6. Initialize AI Gateway with Redis cache (optional - requires Redis)
    ai_gateway = None
    try:
        from app.services.ai_gateway import AIGateway
        from app.services.cache_store import RedisCacheStore

        ai_cfg = cfg.ai
        ai_gateway = AIGateway(
            api_key=ai_cfg.api_key,
            api_url=ai_cfg.api_url,
            model=ai_cfg.model,
            timeout=ai_cfg.timeout,
        )
        if redis_client is not None:
            cache_store = RedisCacheStore(redis_client=redis_client._pool)
            ai_gateway.set_cache_store(cache_store)
        app.state.ai_gateway = ai_gateway
        logger.info(
            "AI Gateway initialized: deepseek=%s, cache=%s",
            ai_gateway.deepseek.is_configured, redis_client is not None,
        )
    except Exception as e:
        logger.warning("AI Gateway initialization failed (non-critical): %s", e)
        app.state.ai_gateway = None

    # Log CORS config
    cors_cfg = cfg.cors
    dev_origins = {"http://localhost:5173", "http://localhost:80"}
    if dev_origins & set(cors_cfg.allow_origins):
        logger.warning(
            "CORS allows development origins: %s. "
            "Restrict to production domains before deployment.",
            dev_origins & set(cors_cfg.allow_origins),
        )
    logger.info(
        "CORS origins: %s, credentials: %s",
        cors_cfg.allow_origins, cors_cfg.allow_credentials,
    )

    yield

    # Shutdown: stop stream consumers
    if metric_aggregator is not None:
        try:
            await metric_aggregator.stop()
            logger.info("Stream consumers stopped")
        except Exception as e:
            logger.warning("Error stopping consumers: %s", e)

    # Shutdown: release ONNX session
    onnx_session_mgr = getattr(app.state, "onnx_session_mgr", None)
    if onnx_session_mgr is not None:
        try:
            onnx_session_mgr.close()
            logger.info("ONNX session released")
        except Exception as e:
            logger.warning("Error releasing ONNX session: %s", e)

    # Shutdown: close AI Gateway
    ai_gw = getattr(app.state, "ai_gateway", None)
    if ai_gw is not None:
        try:
            await ai_gw.close()
            logger.info("AI Gateway closed")
        except Exception as e:
            logger.warning("Error closing AI Gateway: %s", e)

    # Shutdown: flush open segments BEFORE closing Redis/InfluxDB
    logger.info("Shutting down, flushing open segments...")
    try:
        from app.services.worktime_aggregator import save_segment, aggregate_segments
        from app.models.database import get_session
        from app.api.v1.ingest import _get_pipeline

        pipeline = _get_pipeline()
        events = pipeline.flush_all()
        if events:
            session = get_session()
            try:
                for event in events:
                    save_segment(session, event)
                aggregate_segments(session)
            finally:
                session.close()
            logger.info("Flushed %d open segments on shutdown", len(events))
    except Exception as e:
        logger.error("Error flushing segments on shutdown (potential data loss): %s", e)

    # Shutdown: close Redis
    if redis_client is not None:
        try:
            await redis_client.close()
        except Exception as e:
            logger.warning("Error closing Redis: %s", e)

    # Shutdown: close InfluxDB
    if influxdb_client is not None:
        try:
            influxdb_client.close()
        except Exception as e:
            logger.warning("Error closing InfluxDB: %s", e)

    logger.info("Shutdown complete")


# ── App factory ──────────────────────────────────────────────────────────

app = FastAPI(
    title="MES Backend - Edge AI Worktime Analysis",
    description="Action classification, process segmentation, and worktime recording API.",
    version="1.0.0",
    lifespan=lifespan,
)




# ── CORS ─────────────────────────────────────────────────────────────────

cfg = load_app_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors.allow_origins,
    allow_credentials=cfg.cors.allow_credentials,
    allow_methods=cfg.cors.allow_methods,
    allow_headers=cfg.cors.allow_headers,
)


# ── Global exception handler ────────────────────────────────────────────

# AppError registered BEFORE Exception (specific before generic)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """Explicit AppError handler to ensure structured error responses."""
    return JSONResponse(status_code=exc.http_status_code,
                        content=exc.to_dict())


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception on %s %s: %s: %s",
        request.method, request.url, type(exc).__name__, exc,
        exc_info=True,
    )
    # Fallback for unexpected exceptions
    return JSONResponse(
        status_code=500,
        content={
            "code": 50000,
            "message": "Internal server error",
            "data": None,
        },
    )


# ── Routers ─────────────────────────────────────────────────────────────

app.include_router(ingest_router)
app.include_router(worktime_router)
app.include_router(ai_router)
app.include_router(auth_router)
app.include_router(orders_router)
app.include_router(customers_router)
app.include_router(inventory_router)
app.include_router(equipment_router)
app.include_router(reports_router)
app.include_router(dashboard_router)
app.include_router(line_balance_router)
app.include_router(enums_router)
app.include_router(websocket_router)
app.include_router(sse_router)
app.include_router(sse_chat_router)
app.include_router(anomaly_router)
app.include_router(video_router)
app.include_router(quality_router)


# Development/testing: expose a controlled error endpoint to validate global error handling
if bool(os.environ.get("PYTEST_CURRENT_TEST")):
    @app.get("/test/error")
    async def test_error_endpoint():
        from app.core.errors import AppError
        raise AppError("test controlled error", code=9999, http_status_code=418)

# ── Health check ────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "mes-backend", "version": "1.0.0"}


@app.get("/api/v1/ping")
async def ping():
    return {"pong": True}


# ── Prometheus metrics endpoint ──────────────────────────────────

@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
