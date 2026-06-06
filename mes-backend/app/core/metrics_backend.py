"""MetricsBackend Protocol — metrics 写入后端抽象层

定义所有 metrics 写入后端的协议接口，并提供内建实现：
- InfluxBackend: 包装现有 InfluxDB 客户端
- LogBackend: 输出到 stdout JSON，适合开发环境
- NullBackend: 静默丢弃，适合生产降级
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class MetricsBackend(Protocol):
    """所有 metrics 写入后端的协议"""

    def write_metric(
        self, name: str, value: float, tags: dict = None
    ) -> bool: ...

    def query_metric(self, name: str, tags: dict = None) -> list: ...

    def query_raw(self, query: str, org: str = "") -> list:
        """Execute a raw Flux query and return results as dicts.

        Args:
            query: Raw Flux query string.
            org: InfluxDB organization (ignored by non-Influx backends).

        Returns:
            List of result dicts.
        """
        ...


class InfluxBackend:
    """包装现有 InfluxDB 客户端"""

    def __init__(self, client):
        self._client = client

    @property
    def underlying_client(self):
        """Access the underlying InfluxDBClient for advanced operations."""
        return self._client

    def write_metric(
        self, name: str, value: float, tags: dict = None
    ) -> bool:
        """Write a metric to InfluxDB.

        Args:
            name: Metric/measurement name.
            value: Numeric value.
            tags: Optional dict of tag key-value pairs.

        Returns:
            True if write succeeded, False otherwise.
        """
        if self._client is None:
            return False

        try:
            # Use the existing InfluxDB client's write methods
            # Realtime metrics is the closest match for generic metric writes
            station_id = (tags or {}).get("station_id", "unknown")
            shift = (tags or {}).get("shift", "unknown")

            return self._client.write_realtime_metrics(
                station_id=station_id,
                shift=shift,
                human_utilization=value if name == "human_utilization" else 0.0,
                oee=value if name == "oee" else 0.0,
                human_machine_sync=value if name == "human_machine_sync" else 0.0,
                wait_ratio=value if name == "wait_ratio" else 0.0,
                current_action=(tags or {}).get("action", "idle"),
            )
        except Exception as e:
            logger.error("InfluxBackend write failed: %s", e)
            return False

    def query_metric(self, name: str, tags: dict = None) -> list:
        """Query metrics from InfluxDB.

        Args:
            name: Metric/measurement name.
            tags: Optional dict of filter tags.

        Returns:
            List of metric records.
        """
        if self._client is None:
            return []

        try:
            station_id = (tags or {}).get("station_id", "")
            if station_id:
                return self._client.query_latest_metrics(
                    station_id=station_id, window="-1m"
                )
            return []
        except Exception as e:
            logger.error("InfluxBackend query failed: %s", e)
            return []

    def query_raw(self, query: str, org: str = "") -> list:
        """Execute a raw Flux query.

        Args:
            query: Raw Flux query string.
            org: InfluxDB organization (overrides default if provided).

        Returns:
            List of result dicts.
        """
        if self._client is None:
            return []

        try:
            target_org = org or self._client.config.org
            tables = self._client._query_api.query(query, org=target_org)
            return list(self._client._tables_to_dicts(tables))
        except Exception as e:
            logger.error("InfluxBackend query_raw failed: %s", e)
            return []


class LogBackend:
    """输出到 stdout JSON，适合开发环境"""

    def write_metric(
        self, name: str, value: float, tags: dict = None
    ) -> bool:
        """Write metric as JSON log line.

        Args:
            name: Metric name.
            value: Numeric value.
            tags: Optional dict of tag key-value pairs.

        Returns:
            Always True.
        """
        logger.info(
            json.dumps(
                {"metric": name, "value": value, "tags": tags or {}},
                ensure_ascii=False,
            )
        )
        return True

    def query_metric(self, name: str, tags: dict = None) -> list:
        """LogBackend does not support queries.

        Returns:
            Empty list.
        """
        return []

    def query_raw(self, query: str, org: str = "") -> list:
        """LogBackend does not support raw queries.

        Returns:
            Empty list.
        """
        return []


class NullBackend:
    """静默丢弃，适合生产降级"""

    def write_metric(
        self, name: str, value: float, tags: dict = None
    ) -> bool:
        """Discard metric silently.

        Returns:
            Always True (no-op success).
        """
        return True

    def query_metric(self, name: str, tags: dict = None) -> list:
        """Return empty list (no data).

        Returns:
            Empty list.
        """
        return []

    def query_raw(self, query: str, org: str = "") -> list:
        """Return empty list (no data).

        Returns:
            Empty list.
        """
        return []


def create_metrics_backend() -> MetricsBackend:
    """工厂函数：从环境变量选择 backend

    环境变量 METRICS_BACKEND 可选值：
      - "influxdb" (默认): 使用 InfluxDB，不可用时降级到 LogBackend
      - "log": 输出到 stdout JSON
      - "null": 静默丢弃

    Returns:
        配置的 MetricsBackend 实例。
    """
    import os

    backend = os.environ.get("METRICS_BACKEND", "influxdb")

    if backend == "log":
        return LogBackend()
    elif backend == "null":
        return NullBackend()

    # default: InfluxBackend
    try:
        from app.core.influxdb_client import InfluxDBClient
        from app.core.config import InfluxDBConfig

        config = InfluxDBConfig()
        client = InfluxDBClient(config)
        return InfluxBackend(client)
    except Exception:
        logger.warning("InfluxDB unavailable, falling back to LogBackend")
        return LogBackend()
