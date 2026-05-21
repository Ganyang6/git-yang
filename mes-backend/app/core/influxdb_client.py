"""
InfluxDB client wrapper for MES backend.

Provides:
  - InfluxDBClient: async-ready client using influxdb-client Python library
  - Batch write helpers for pose_landmarks, action_classifications, realtime_metrics, etc.
  - Query helpers for real-time and historical data retrieval
  - Bucket initialization and retention policy management
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from app.core.config import InfluxDBConfig

logger = logging.getLogger("mes_backend.influxdb")

# Thread pool for running blocking InfluxDB operations in async context
_db_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="influxdb_io")

# Input validation patterns for Flux query parameters.
# Prevents Flux injection when user-supplied values are interpolated into queries.
_RE_STATION_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_RE_TIME_WINDOW = re.compile(r"^-[0-9]+[smhdw]$")
_RE_AGG_FUNC = re.compile(r"^(mean|max|min|sum|count|median|stddev)$")
_RE_EVERY = re.compile(r"^[0-9]+[smhdw]$")


# Measurement name constants
MEASUREMENT_POSE_LANDMARKS = "pose_landmarks"
MEASUREMENT_ACTION_CLASSIFICATIONS = "action_classifications"
MEASUREMENT_REALTIME_METRICS = "realtime_metrics"
MEASUREMENT_SEGMENT_EVENTS = "segment_events"
MEASUREMENT_THERBLIG_DISTRIBUTION = "therblig_distribution"
MEASUREMENT_SYSTEM_HEALTH = "system_health"


class InfluxDBClient:
    """
    InfluxDB client for MES time-series data.

    Handles batch writes, common queries, and bucket initialization.
    Uses influxdb-client (InfluxDB 2.x) with retry logic.

    Usage:
        client = InfluxDBClient(config)
        client.initialize()
        client.write_landmark_point(camera_id="cam_01", landmark_name="LEFT_WRIST", ...)
        results = client.query_latest_metrics(station_id="station_03")
        client.close()
    """

    def __init__(self, config: Optional[InfluxDBConfig] = None) -> None:
        self.config = config or InfluxDBConfig()
        self._write_api = None
        self._query_api = None
        self._client = None
        self._max_retries = self.config.max_retries or 3

    @property
    def is_initialized(self) -> bool:
        return self._client is not None

    def initialize(self) -> bool:
        """
        Initialize InfluxDB client, create bucket if not exists.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        try:
            from influxdb_client import InfluxDBClient as InfluxClient
            from influxdb_client import WriteOptions
            from influxdb_client.client.write_api import SYNCHRONOUS

            self._client = InfluxClient(
                url=self.config.url,
                token=self.config.token,
                org=self.config.org,
                timeout=self.config.timeout or 5000,
                client_session_kwargs={"max_pool_size": self.config.max_pool_size},
            )

            # Create buckets API
            buckets_api = self._client.buckets_api()

            # Ensure hot bucket exists
            self._ensure_bucket(buckets_api, self.config.org, self.config.bucket, self.config.hot_retention_days)
            # Ensure long-term bucket exists
            self._ensure_bucket(buckets_api, self.config.org, self.config.longterm_bucket, self.config.longterm_retention_days)

            # Initialize write and query APIs
            write_options = WriteOptions(
                batch_size=self.config.write_batch_size,
                flush_interval=self.config.write_flush_interval_ms,
            )
            self._write_api = self._client.write_api(
                write_options=write_options, write_precision=self.config.write_precision
            )
            self._query_api = self._client.query_api()

            # Verify connectivity
            self._client.health()
            logger.info(
                "InfluxDB connected: %s, org=%s, bucket=%s",
                self.config.url, self.config.org, self.config.bucket,
            )
            return True

        except Exception as e:
            self._client = None
            self._write_api = None
            self._query_api = None
            logger.error("InfluxDB initialization failed: %s", e)
            return False

    def _ensure_bucket(self, buckets_api, org: str, bucket_name: str, retention_days: int) -> None:
        """Create bucket if it does not exist."""
        try:
            existing = buckets_api.find_bucket_by_name(bucket_name)
            if existing:
                logger.debug("Bucket '%s' already exists", bucket_name)
                return
        except requests.exceptions.ConnectionError:
            logger.warning("InfluxDB not reachable, cannot ensure bucket")
            return
        except Exception as e:
            logger.error("Failed to check bucket %s: %s", bucket_name, e)
            return

        from influxdb_client import Bucket, BucketRetentionRules

        retention_rules = BucketRetentionRules(
            type="expire",
            every_seconds=retention_days * 86400,
        )
        buckets_api.create_bucket(
            bucket_name=bucket_name,
            retention_rules=retention_rules,
            org=self.config.org,
        )
        logger.info("Created bucket '%s' with %dd retention", bucket_name, retention_days)

    def close(self) -> None:
        """Close the InfluxDB client."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self._write_api = None
            self._query_api = None
            logger.info("InfluxDB connection closed")

    def _write_with_retry(self, bucket: str, record: Any) -> bool:
        """
        Write data with retry logic.

        Args:
            bucket: Target bucket name.
            record: Point object, list of Points, or Line Protocol string.

        Returns:
            True if write succeeded, False otherwise.
        """
        if self._write_api is None:
            logger.error("InfluxDB write API not initialized")
            return False

        retry_count = 0
        while retry_count <= self._max_retries:
            try:
                self._write_api.write(bucket=bucket, record=record)
                return True
            except Exception as e:
                retry_count += 1
                if retry_count > self._max_retries:
                    logger.error(
                        "InfluxDB write failed after %d attempts: %s",
                        self._max_retries, e,
                    )
                    return False
                wait = 2 ** (retry_count - 1)
                logger.warning(
                    "InfluxDB write failed (attempt %d/%d), retrying in %ds: %s",
                    retry_count, self._max_retries, wait, e,
                )
                time.sleep(wait)

    def _make_point(
        self,
        measurement: str,
        tags: Dict[str, str],
        fields: Dict[str, Any],
        timestamp_ms: Optional[int] = None,
    ):
        """Create a Point object for InfluxDB write."""
        from influxdb_client import Point

        point = Point(measurement)
        for k, v in tags.items():
            point.tag(k, str(v))
        for k, v in fields.items():
            if isinstance(v, str):
                point.field(k, v)
            elif isinstance(v, (int, float)):
                point.field(k, v)
            elif isinstance(v, bool):
                point.field(k, v)
            else:
                point.field(k, str(v))

        if timestamp_ms is not None:
            point.time(timestamp_ms, self.config.write_precision)
        else:
            point.time(int(time.time() * 1000), self.config.write_precision)

        return point

    # ── Pose Landmark Writes ─────────────────────────────────────────────

    def write_landmark_points(
        self,
        points_data: List[Dict[str, Any]],
    ) -> bool:
        """
        Write pose landmark data in batch.

        Each item in points_data should be a dict with:
          camera_id, landmark_name, avg_x, avg_y, avg_z, avg_visibility, sample_count, timestamp_ms

        Returns:
            True if write succeeded.
        """
        if not points_data or self._write_api is None:
            return False

        from influxdb_client import Point

        points = []
        for d in points_data:
            p = Point(MEASUREMENT_POSE_LANDMARKS)
            p.tag("camera_id", d["camera_id"])
            p.tag("landmark_name", d["landmark_name"])
            p.field("avg_x", float(d["avg_x"]))
            p.field("avg_y", float(d["avg_y"]))
            p.field("avg_z", float(d["avg_z"]))
            p.field("avg_visibility", float(d["avg_visibility"]))
            p.field("sample_count", int(d.get("sample_count", 1)))
            ts = d.get("timestamp_ms") or int(time.time() * 1000)
            p.time(int(ts), self.config.write_precision)
            points.append(p)

        return self._write_with_retry(self.config.bucket, points)

    # ── Action Classification Writes ─────────────────────────────────────

    def write_action_classification(
        self,
        camera_id: str,
        station_id: str,
        action: str,
        confidence: float,
        dominant_region: str = "none",
        duration_in_window_ms: float = 0.0,
        window_size: int = 30,
        timestamp_ms: Optional[int] = None,
    ) -> bool:
        """Write a single action classification point."""
        point = self._make_point(
            MEASUREMENT_ACTION_CLASSIFICATIONS,
            tags={
                "camera_id": camera_id,
                "station_id": station_id,
                "action": action,
                "dominant_region": dominant_region,
            },
            fields={
                "confidence": float(confidence),
                "duration_in_window_ms": float(duration_in_window_ms),
                "window_size": int(window_size),
            },
            timestamp_ms=timestamp_ms,
        )
        return self._write_with_retry(self.config.bucket, point)

    # ── Real-time Metrics Writes ─────────────────────────────────────────

    def write_realtime_metrics(
        self,
        station_id: str,
        shift: str,
        human_utilization: float,
        oee: float,
        human_machine_sync: float,
        wait_ratio: float,
        current_action: str = "idle",
        segment_duration_ms: float = 0.0,
        line_balance_rate: Optional[float] = None,
        smoothness_index: Optional[float] = None,
        bottleneck_flag: int = 0,
        timestamp_ms: Optional[int] = None,
    ) -> bool:
        """Write a single real-time metrics point."""
        fields: Dict[str, Any] = {
            "human_utilization": float(human_utilization),
            "oee": float(oee),
            "human_machine_sync": float(human_machine_sync),
            "wait_ratio": float(wait_ratio),
            "current_action": str(current_action),
            "segment_duration_ms": float(segment_duration_ms),
            "bottleneck_flag": int(bottleneck_flag),
        }
        if line_balance_rate is not None:
            fields["line_balance_rate"] = float(line_balance_rate)
        if smoothness_index is not None:
            fields["smoothness_index"] = float(smoothness_index)

        point = self._make_point(
            MEASUREMENT_REALTIME_METRICS,
            tags={"station_id": station_id, "shift": shift},
            fields=fields,
            timestamp_ms=timestamp_ms,
        )
        return self._write_with_retry(self.config.bucket, point)

    # ── Segment Event Writes ─────────────────────────────────────────────

    def write_segment_event(
        self,
        camera_id: str,
        station_id: str,
        action: str,
        therblig_symbol: str,
        shift: str,
        duration_ms: float,
        confidence: float,
        mod_value: float = 0.0,
        standard_ms: float = 0.0,
        is_waste: int = 0,
        timestamp_ms: Optional[int] = None,
    ) -> bool:
        """Write a single segment event point."""
        point = self._make_point(
            MEASUREMENT_SEGMENT_EVENTS,
            tags={
                "camera_id": camera_id,
                "station_id": station_id,
                "action": action,
                "therblig_symbol": therblig_symbol,
                "shift": shift,
            },
            fields={
                "duration_ms": float(duration_ms),
                "confidence": float(confidence),
                "mod_value": float(mod_value),
                "standard_ms": float(standard_ms),
                "is_waste": int(is_waste),
            },
            timestamp_ms=timestamp_ms,
        )
        return self._write_with_retry(self.config.bucket, point)

    # ── System Health Writes ─────────────────────────────────────────────

    def write_system_health(
        self,
        service: str,
        cpu_usage: float = 0.0,
        memory_mb: float = 0.0,
        active_connections: int = 0,
        request_latency_ms: float = 0.0,
        error_rate: float = 0.0,
        uptime_seconds: int = 0,
        **extra_fields: Any,
    ) -> bool:
        """Write a system health data point."""
        fields: Dict[str, Any] = {
            "cpu_usage": float(cpu_usage),
            "memory_mb": float(memory_mb),
            "active_connections": int(active_connections),
            "request_latency_ms": float(request_latency_ms),
            "error_rate": float(error_rate),
            "uptime_seconds": int(uptime_seconds),
        }
        fields.update(extra_fields)

        point = self._make_point(
            MEASUREMENT_SYSTEM_HEALTH,
            tags={"service": service},
            fields=fields,
        )
        return self._write_with_retry(self.config.bucket, point)

    # ── Query Helpers ────────────────────────────────────────────────────

    def query_latest_metrics(
        self,
        station_id: str,
        window: str = "-10s",
    ) -> List[Dict[str, Any]]:
        """
        Query the latest metrics for a station.

        Args:
            station_id: Target station.
            window: InfluxDB time range (e.g., "-10s", "-1m").

        Returns:
            List of metric records with field values.
        """
        if self._query_api is None:
            return []

        if not _RE_STATION_ID.match(station_id):
            logger.warning("query_latest_metrics: invalid station_id rejected: %r", station_id)
            return []
        if not _RE_TIME_WINDOW.match(window):
            logger.warning("query_latest_metrics: invalid window rejected: %r", window)
            return []

        query = f"""
        from(bucket: "{self.config.bucket}")
          |> range(start: {window})
          |> filter(fn: (r) => r._measurement == "{MEASUREMENT_REALTIME_METRICS}")
          |> filter(fn: (r) => r.station_id == "{station_id}")
          |> last()
        """
        try:
            tables = self._query_api.query(query, org=self.config.org)
            return self._tables_to_dicts(tables)
        except Exception as e:
            logger.error("Failed to query latest metrics: %s", e)
            return []

    def query_aggregated_metrics(
        self,
        station_id: str,
        window: str = "-1h",
        agg: str = "mean",
        every: str = "1m",
    ) -> List[Dict[str, Any]]:
        """
        Query aggregated metrics for a station.

        Args:
            station_id: Target station.
            window: Time range.
            agg: Aggregation function (mean, max, min).
            every: Aggregation window.

        Returns:
            List of aggregated metric records.
        """
        if self._query_api is None:
            return []

        if not _RE_STATION_ID.match(station_id):
            logger.warning("query_aggregated_metrics: invalid station_id rejected: %r", station_id)
            return []
        if not _RE_TIME_WINDOW.match(window):
            logger.warning("query_aggregated_metrics: invalid window rejected: %r", window)
            return []
        if not _RE_AGG_FUNC.match(agg):
            logger.warning("query_aggregated_metrics: invalid agg rejected: %r", agg)
            return []
        if not _RE_EVERY.match(every):
            logger.warning("query_aggregated_metrics: invalid every rejected: %r", every)
            return []

        query = f"""
        from(bucket: "{self.config.bucket}")
          |> range(start: {window})
          |> filter(fn: (r) => r._measurement == "{MEASUREMENT_REALTIME_METRICS}")
          |> filter(fn: (r) => r.station_id == "{station_id}")
          |> aggregateWindow(every: {every}, fn: {agg})
        """
        try:
            tables = self._query_api.query(query, org=self.config.org)
            return self._tables_to_dicts(tables)
        except Exception as e:
            logger.error("Failed to query aggregated metrics: %s", e)
            return []

    def query_segment_events(
        self,
        station_id: str,
        window: str = "-8h",
    ) -> List[Dict[str, Any]]:
        """Query segment events for a station."""
        if self._query_api is None:
            return []

        if not _RE_STATION_ID.match(station_id):
            logger.warning("query_segment_events: invalid station_id rejected: %r", station_id)
            return []
        if not _RE_TIME_WINDOW.match(window):
            logger.warning("query_segment_events: invalid window rejected: %r", window)
            return []

        query = f"""
        from(bucket: "{self.config.bucket}")
          |> range(start: {window})
          |> filter(fn: (r) => r._measurement == "{MEASUREMENT_SEGMENT_EVENTS}")
          |> filter(fn: (r) => r.station_id == "{station_id}")
          |> sort(columns: ["_time"])
        """
        try:
            tables = self._query_api.query(query, org=self.config.org)
            return self._tables_to_dicts(tables)
        except Exception as e:
            logger.error("Failed to query segment events: %s", e)
            return []

    def query_health(self) -> bool:
        """Check if InfluxDB is responsive."""
        if self._client is None:
            return False
        try:
            self._client.health()
            return True
        except Exception:
            return False

    @staticmethod
    def _tables_to_dicts(tables) -> List[Dict[str, Any]]:
        """Convert InfluxDB query result tables to list of dicts."""
        results: List[Dict[str, Any]] = []
        for table in tables:
            for record in table.records:
                row: Dict[str, Any] = {}
                row["time"] = record.get_time()
                row["measurement"] = record.get_measurement()
                for key in record.values:
                    if key not in ("result", "_time", "_measurement", "table"):
                        row[key] = record.values[key]
                results.append(row)
        return results
