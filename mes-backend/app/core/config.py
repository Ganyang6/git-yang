"""
Application configuration

Extends the existing perception config (config.py at mes-backend root)
with FastAPI, database, action classification and process segmentation
settings.  Loads from config.yaml and environment variables.

Infrastructure URLs (Redis, InfluxDB, Celery, Database) intentionally
default to empty strings.  The runtime priority chain is:
    config.yaml > environment variable > empty (fail/warn at startup)
This prevents silent fallback to localhost values that work in dev but
break in production deployments.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    """SQLite database settings.

    url must be provided via config.yaml app.database.url or MES_DB_URL
    environment variable.  Empty default forces explicit configuration.
    """
    url: str = ""
    echo: bool = False  # SQL logging for debug


@dataclass
class ActionClassifierConfig:
    """Rule-based action classification settings."""
    # Sliding window: number of frames to accumulate before classification
    window_size: int = 10  # 10 frames at 30fps = 1/3 second
    # Minimum visibility threshold for a landmark to be considered valid
    min_landmark_visibility: float = 0.5
    # Minimum number of visible body landmarks required to attempt classification
    min_visible_landmarks: int = 10


@dataclass
class ProcessSegmenterConfig:
    """State-machine process segmentation settings."""
    # Number of consecutive identical predictions required to confirm an action change
    confirmation_frames: int = 5
    # If no valid pose is received for this many frames, emit an "idle" event
    idle_timeout_frames: int = 30  # 1 second at 30fps
    # Maximum duration for a single process segment (seconds). Segments exceeding
    # this will be force-split to prevent extremely long stuck segments.
    max_segment_duration_s: float = 300.0


@dataclass
class TherbligConfig:
    """Therblig (motion element) analysis settings."""
    # MOD unit multiplier: 1 MOD = 0.129 seconds
    mod_unit_seconds: float = 0.129


@dataclass
class AiConfig:
    """AI chat proxy settings."""
    # DeepSeek API key (read from env DEEPSEEK_API_KEY or config.yaml)
    api_key: str = ""
    # DeepSeek API base URL (read from env DEEPSEEK_API_URL or config.yaml)
    api_url: str = ""
    # Model name
    model: str = "deepseek-chat"
    # Request timeout in seconds
    timeout: int = 30


@dataclass
class AuthConfig:
    """JWT authentication settings (spec_security_auth.md)."""
    # HMAC-SHA256 signing key, from env JWT_SECRET_KEY or config.yaml
    jwt_secret_key: str = ""
    # Default token expiry in hours (8h matches longest shift)
    token_expire_hours: int = 8
    # "Remember me" token expiry in days
    token_remember_days: int = 7
    # Fixed users (Phase 3: config-based, not database-based)
    # Loaded from config.yaml -> app.auth.users
    users: Optional[List[dict]] = None


@dataclass
class StreamConsumerConfig:
    """Redis Stream consumer settings."""
    # 惰性聚合阈值：累计多少条未聚合记录后触发 aggregate_segments()
    aggregation_threshold: int = 50


@dataclass
class CorsConfig:
    """CORS middleware settings."""
    # List of allowed origins. Use ["*"] for development only.
    allow_origins: List[str] = field(default_factory=lambda: ["http://localhost:5173", "http://localhost:80", "http://localhost"])
    # Whether to allow cookies/credentials in cross-origin requests
    allow_credentials: bool = False
    # Allowed HTTP methods
    allow_methods: List[str] = field(default_factory=lambda: ["GET", "POST", "PUT", "DELETE"])
    # Allowed request headers
    allow_headers: List[str] = field(default_factory=lambda: ["Content-Type", "Authorization"])


@dataclass
class RedisConfig:
    """Redis connection and stream settings.

    url must be provided via config.yaml app.redis.url or REDIS_URL
    environment variable.  Empty default forces explicit configuration.
    """
    url: str = ""
    # Connection pool settings
    max_connections: int = 50
    # Connection timeout settings
    socket_connect_timeout: int = 5
    socket_timeout: int = 3
    # Stream maxlen settings
    pose_stream_maxlen: int = 3600
    action_stream_maxlen: int = 86400
    metrics_stream_maxlen: int = 600
    analysis_tasks_stream_maxlen: int = 1000
    analysis_results_stream_maxlen: int = 1000
    system_events_stream_maxlen: int = 10000
    # Consumer group names
    consumer_group_classifier: str = "cg:action_classifier"
    consumer_group_metrics: str = "cg:metric_calculator"
    consumer_group_ws: str = "cg:websocket_pusher"
    consumer_group_celery: str = "cg:celery_worker"
    consumer_group_ws_notifier: str = "cg:ws_notifier"
    consumer_group_sys_monitor: str = "cg:sys_monitor"
    # PEL reclaim
    pel_reclaim_min_idle_ms: int = 60000
    pel_max_claim_count: int = 100
    # Dead letter
    dead_letter_max_retries: int = 3


@dataclass
class CeleryConfig:
    """Celery async task processing settings.

    broker_url and result_backend must be provided via config.yaml or
    environment variables (CELERY_BROKER_URL, CELERY_RESULT_BACKEND).
    """
    broker_url: str = ""
    result_backend: str = ""
    task_serializer: str = "json"
    result_serializer: str = "json"
    accept_content: list[str] = field(default_factory=lambda: ["json"])
    result_expires: int = 3600
    worker_max_tasks_per_child: int = 500
    worker_max_memory_per_child: int = 300_000
    worker_eta_task_limit: int = 1000
    timezone: str = "Asia/Shanghai"
    enable_utc: bool = True


@dataclass
class InfluxDBConfig:
    """InfluxDB connection and write settings.

    url must be provided via config.yaml app.influxdb.url or INFLUXDB_URL
    environment variable.  Empty default forces explicit configuration.
    """
    url: str = ""
    token: str = ""
    org: str = "mes-factory"
    bucket: str = "metrics"
    longterm_bucket: str = "metrics_longterm"
    write_batch_size: int = 500
    write_flush_interval_ms: int = 10000
    hot_retention_days: int = 30
    longterm_retention_days: int = 365
    landmark_retention_days: int = 7
    write_precision: str = "ms"
    # Connection timeout in milliseconds
    timeout: int = 5000
    # Max retries for write operations
    max_retries: int = 3
    # Connection pool size limit
    max_pool_size: int = 10


@dataclass
class OnnxConfig:
    """ONNX Runtime inference settings."""
    # Relative path from the project root to the ONNX model file
    model_path: str = "models/action_classifier_latest.onnx"
    confidence_threshold: float = 0.7
    sha256_checksum: Optional[str] = None


@dataclass
class AppConfig:
    """Root application configuration."""
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    action_classifier: ActionClassifierConfig = field(
        default_factory=ActionClassifierConfig
    )
    process_segmenter: ProcessSegmenterConfig = field(
        default_factory=ProcessSegmenterConfig
    )
    therblig: TherbligConfig = field(default_factory=TherbligConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    stream_consumer: StreamConsumerConfig = field(default_factory=StreamConsumerConfig)
    cors: CorsConfig = field(default_factory=CorsConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    celery: CeleryConfig = field(default_factory=CeleryConfig)
    influxdb: InfluxDBConfig = field(default_factory=InfluxDBConfig)
    onnx: OnnxConfig = field(default_factory=OnnxConfig)


@lru_cache(maxsize=1)
def _env_or_file(key: str, default: str = "") -> str:
    """Get value from env var, falling back to *_FILE env var for Docker secrets.

    Supports the Docker secrets convention: if KEY env var is unset,
    checks KEY_FILE env var for a path to a Docker secrets file mounted
    at /run/secrets/<name>.

    Args:
        key: Environment variable name (e.g. "JWT_SECRET_KEY").
        default: Default value if neither env var nor file is available.

    Returns:
        The secret value as a string, or default if not found.
    """
    val = os.environ.get(key)
    if val:
        return val
    file_key = f"{key}_FILE"
    file_path = os.environ.get(file_key)
    if file_path:
        try:
            return Path(file_path).read_text().strip()
        except (OSError, IOError):
            logger.debug("Docker secrets file not readable: %s", file_path)
    return default


def _validate_critical_configs(config: AppConfig) -> None:
    """Log warnings for empty infrastructure URLs that may cause issues.

    Database URL is required (WARNING level).  Redis, InfluxDB, and Celery
    are optional services with graceful degradation (INFO level).
    """
    if not config.database.url:
        logger.warning(
            "Database URL is empty. Set app.database.url in config.yaml "
            "or MES_DB_URL environment variable."
        )
    if not config.redis.url:
        logger.info(
            "Redis URL is empty. Redis-dependent features disabled. "
            "Set app.redis.url in config.yaml or REDIS_URL env var."
        )
    if not config.influxdb.url:
        logger.info(
            "InfluxDB URL is empty. Metrics storage disabled. "
            "Set app.influxdb.url in config.yaml or INFLUXDB_URL env var."
        )
    if not config.celery.broker_url:
        logger.info(
            "Celery broker URL is empty. Async task processing disabled. "
            "Set app.celery.broker_url in config.yaml or CELERY_BROKER_URL env var."
        )


@lru_cache(maxsize=1)
def load_app_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Load application configuration from a YAML file.

    Args:
        config_path: Path to the YAML config file. If None, looks for
                     config.yaml in the mes-backend root.

    Returns:
        AppConfig instance with loaded values, or defaults if file not found.
    """
    if config_path is None:
        config_path = str(Path(__file__).parent.parent.parent / "config.yaml")

    path = Path(config_path)
    if not path.exists():
        return AppConfig()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return AppConfig()

    if not isinstance(data, dict):
        return AppConfig()

    config = AppConfig()

    app_cfg = data.get("app", {})
    db_cfg = app_cfg.get("database", {})
    config.database = DatabaseConfig(
        url=db_cfg.get("url", config.database.url),
        echo=db_cfg.get("echo", config.database.echo),
    )

    ac_cfg = app_cfg.get("action_classifier", {})
    config.action_classifier = ActionClassifierConfig(
        window_size=ac_cfg.get("window_size", config.action_classifier.window_size),
        min_landmark_visibility=ac_cfg.get(
            "min_landmark_visibility", config.action_classifier.min_landmark_visibility
        ),
        min_visible_landmarks=ac_cfg.get(
            "min_visible_landmarks", config.action_classifier.min_visible_landmarks
        ),
    )

    ps_cfg = app_cfg.get("process_segmenter", {})
    config.process_segmenter = ProcessSegmenterConfig(
        confirmation_frames=ps_cfg.get(
            "confirmation_frames", config.process_segmenter.confirmation_frames
        ),
        idle_timeout_frames=ps_cfg.get(
            "idle_timeout_frames", config.process_segmenter.idle_timeout_frames
        ),
        max_segment_duration_s=ps_cfg.get(
            "max_segment_duration_s", config.process_segmenter.max_segment_duration_s
        ),
    )

    th_cfg = app_cfg.get("therblig", {})
    config.therblig = TherbligConfig(
        mod_unit_seconds=th_cfg.get(
            "mod_unit_seconds", config.therblig.mod_unit_seconds
        ),
    )

    ai_cfg = app_cfg.get("ai", {})
    config.ai = AiConfig(
        api_key=ai_cfg.get("api_key", _env_or_file("DEEPSEEK_API_KEY", config.ai.api_key)),
        api_url=ai_cfg.get("api_url", os.environ.get("DEEPSEEK_API_URL", config.ai.api_url)),
        model=ai_cfg.get("model", config.ai.model),
        timeout=ai_cfg.get("timeout", config.ai.timeout),
    )

    auth_cfg = app_cfg.get("auth", {})
    config.auth = AuthConfig(
        jwt_secret_key=auth_cfg.get(
            "jwt_secret_key",
            _env_or_file("JWT_SECRET_KEY", config.auth.jwt_secret_key),
        ),
        token_expire_hours=auth_cfg.get("token_expire_hours", config.auth.token_expire_hours),
        token_remember_days=auth_cfg.get("token_remember_days", config.auth.token_remember_days),
        users=auth_cfg.get("users", config.auth.users),
    )

    cors_cfg = app_cfg.get("cors", {})
    config.cors = CorsConfig(
        allow_origins=cors_cfg.get("allow_origins", config.cors.allow_origins),
        allow_credentials=cors_cfg.get("allow_credentials", config.cors.allow_credentials),
        allow_methods=cors_cfg.get("allow_methods", config.cors.allow_methods),
        allow_headers=cors_cfg.get("allow_headers", config.cors.allow_headers),
    )

    sc_cfg = app_cfg.get("stream_consumer", {})
    config.stream_consumer = StreamConsumerConfig(
        aggregation_threshold=sc_cfg.get(
            "aggregation_threshold", config.stream_consumer.aggregation_threshold
        ),
    )

    redis_cfg = app_cfg.get("redis", {})
    config.redis = RedisConfig(
        url=redis_cfg.get("url", os.environ.get("REDIS_URL", config.redis.url)),
        socket_connect_timeout=redis_cfg.get("socket_connect_timeout", config.redis.socket_connect_timeout),
        socket_timeout=redis_cfg.get("socket_timeout", config.redis.socket_timeout),
        pose_stream_maxlen=redis_cfg.get("pose_stream_maxlen", config.redis.pose_stream_maxlen),
        action_stream_maxlen=redis_cfg.get("action_stream_maxlen", config.redis.action_stream_maxlen),
        metrics_stream_maxlen=redis_cfg.get("metrics_stream_maxlen", config.redis.metrics_stream_maxlen),
    )

    celery_cfg = app_cfg.get("celery", {})
    config.celery = CeleryConfig(
        broker_url=celery_cfg.get(
            "broker_url",
            os.environ.get("CELERY_BROKER_URL", config.celery.broker_url),
        ),
        result_backend=celery_cfg.get(
            "result_backend",
            os.environ.get("CELERY_RESULT_BACKEND", config.celery.result_backend),
        ),
        result_expires=celery_cfg.get("result_expires", config.celery.result_expires),
        worker_max_tasks_per_child=celery_cfg.get(
            "worker_max_tasks_per_child", config.celery.worker_max_tasks_per_child,
        ),
        worker_max_memory_per_child=celery_cfg.get(
            "worker_max_memory_per_child", config.celery.worker_max_memory_per_child,
        ),
    )

    onnx_cfg = app_cfg.get("onnx", {})
    config.onnx = OnnxConfig(
        model_path=onnx_cfg.get("model_path", config.onnx.model_path),
        confidence_threshold=onnx_cfg.get(
            "confidence_threshold", config.onnx.confidence_threshold,
        ),
        sha256_checksum=onnx_cfg.get("sha256_checksum", config.onnx.sha256_checksum),
    )

    influx_cfg = app_cfg.get("influxdb", {})
    config.influxdb = InfluxDBConfig(
        url=influx_cfg.get("url", os.environ.get("INFLUXDB_URL", config.influxdb.url)),
        token=influx_cfg.get("token", _env_or_file("INFLUXDB_TOKEN", config.influxdb.token)),
        org=influx_cfg.get("org", config.influxdb.org),
        bucket=influx_cfg.get("bucket", config.influxdb.bucket),
        write_batch_size=influx_cfg.get("write_batch_size", config.influxdb.write_batch_size),
        write_flush_interval_ms=influx_cfg.get("write_flush_interval_ms", config.influxdb.write_flush_interval_ms),
        max_pool_size=influx_cfg.get("max_pool_size", config.influxdb.max_pool_size),
    )

    _validate_critical_configs(config)

    return config



