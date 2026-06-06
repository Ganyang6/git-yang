"""Tests for MetricsBackend Protocol and implementations."""

import os
import json
import logging
from io import StringIO

import pytest

from app.core.metrics_backend import (
    MetricsBackend,
    InfluxBackend,
    LogBackend,
    NullBackend,
    create_metrics_backend,
)


class TestMetricsBackendProtocol:
    """Verify that MetricsBackend is a proper Protocol type."""

    def test_metrics_backend_is_protocol(self):
        """MetricsBackend should be a class defining a Protocol."""
        assert isinstance(MetricsBackend, type)

    def test_metrics_backend_has_write_metric_signature(self):
        """MetricsBackend should define write_metric method."""
        assert hasattr(MetricsBackend, "write_metric")
        assert callable(MetricsBackend.write_metric)

    def test_metrics_backend_has_query_metric_signature(self):
        """MetricsBackend should define query_metric method."""
        assert hasattr(MetricsBackend, "query_metric")
        assert callable(MetricsBackend.query_metric)

    def test_metrics_backend_has_query_raw_signature(self):
        """MetricsBackend should define query_raw method."""
        assert hasattr(MetricsBackend, "query_raw")
        assert callable(MetricsBackend.query_raw)


class TestInfluxBackend:
    """Tests for InfluxBackend wrapper."""

    def test_influx_backend_has_write_metric(self):
        """InfluxBackend should have write_metric method."""
        # Create with None client to test signature only
        backend = InfluxBackend(client=None)
        assert hasattr(backend, "write_metric")
        assert callable(backend.write_metric)

    def test_influx_backend_has_query_metric(self):
        """InfluxBackend should have query_metric method."""
        backend = InfluxBackend(client=None)
        assert hasattr(backend, "query_metric")
        assert callable(backend.query_metric)

    def test_influx_backend_write_metric_without_client(self):
        """InfluxBackend without a client should return False."""
        backend = InfluxBackend(client=None)
        result = backend.write_metric("test", 1.0, {"tag": "val"})
        assert result is False

    def test_influx_backend_query_metric_without_client(self):
        """InfluxBackend without a client should return empty list."""
        backend = InfluxBackend(client=None)
        result = backend.query_metric("test", {"tag": "val"})
        assert result == []

    def test_influx_backend_has_query_raw(self):
        """InfluxBackend should have query_raw method."""
        backend = InfluxBackend(client=None)
        assert hasattr(backend, "query_raw")
        assert callable(backend.query_raw)

    def test_influx_backend_query_raw_without_client(self):
        """InfluxBackend without a client should return empty list."""
        backend = InfluxBackend(client=None)
        result = backend.query_raw("from(bucket: \"test\") |> range(start: -1h)")
        assert result == []

    def test_influx_backend_underlying_client_property(self):
        """InfluxBackend should expose underlying_client property."""
        backend = InfluxBackend(client=None)
        assert backend.underlying_client is None


class TestLogBackend:
    """Tests for LogBackend - writes metrics to stdout JSON."""

    def test_log_backend_has_write_metric(self):
        """LogBackend should have write_metric."""
        backend = LogBackend()
        assert hasattr(backend, "write_metric")

    def test_log_backend_has_query_metric(self):
        """LogBackend should have query_metric."""
        backend = LogBackend()
        assert hasattr(backend, "query_metric")

    def test_log_backend_write_simple_metric(self):
        """LogBackend.write_metric should return True always."""
        backend = LogBackend()
        result = backend.write_metric("test_metric", 42.0, {"env": "test"})
        assert result is True

    def test_log_backend_query_metric_returns_empty(self):
        """LogBackend.query_metric should return empty list."""
        backend = LogBackend()
        result = backend.query_metric("test")
        assert result == []

    def test_log_backend_query_raw_returns_empty(self):
        """LogBackend.query_raw should return empty list."""
        backend = LogBackend()
        result = backend.query_raw("some query")
        assert result == []

    def test_log_backend_writes_json_to_logger(self, caplog):
        """LogBackend should output JSON to the logger."""
        caplog.set_level(logging.INFO)
        backend = LogBackend()
        backend.write_metric("cpu_usage", 75.5, {"host": "server01"})
        assert len(caplog.records) >= 1
        last_record = caplog.records[-1]
        # Should contain valid JSON with our metric name and value
        assert "cpu_usage" in last_record.getMessage()
        assert "75.5" in last_record.getMessage()
        # Verify it's valid JSON
        parsed = json.loads(last_record.getMessage())
        assert parsed["metric"] == "cpu_usage"
        assert parsed["value"] == 75.5
        assert parsed["tags"]["host"] == "server01"


class TestNullBackend:
    """Tests for NullBackend - silently discards metrics."""

    def test_null_backend_has_write_metric(self):
        """NullBackend should have write_metric."""
        backend = NullBackend()
        assert hasattr(backend, "write_metric")

    def test_null_backend_has_query_metric(self):
        """NullBackend should have query_metric."""
        backend = NullBackend()
        assert hasattr(backend, "query_metric")

    def test_null_backend_write_metric_returns_true(self):
        """NullBackend.write_metric should return True without doing anything."""
        backend = NullBackend()
        result = backend.write_metric("any_metric", 99.9, {"any": "tag"})
        assert result is True

    def test_null_backend_query_metric_returns_empty_list(self):
        """NullBackend.query_metric should return empty list."""
        backend = NullBackend()
        result = backend.query_metric("any_metric", {"any": "tag"})
        assert result == []

    def test_null_backend_query_raw_returns_empty_list(self):
        """NullBackend.query_raw should return empty list."""
        backend = NullBackend()
        result = backend.query_raw("any query")
        assert result == []

    def test_null_backend_does_not_log(self, caplog):
        """NullBackend should produce no log output."""
        caplog.set_level(logging.INFO)
        backend = NullBackend()
        backend.write_metric("secret", 42.0)
        # NullBackend should not generate any log records
        log_messages = [r.getMessage() for r in caplog.records]
        # None of them should contain our metric name
        assert not any("secret" in msg for msg in log_messages)


class TestCreateMetricsBackend:
    """Tests for create_metrics_backend factory function."""

    def test_create_metrics_backend_from_log_env(self, monkeypatch):
        """METRICS_BACKEND=log should return LogBackend."""
        monkeypatch.setenv("METRICS_BACKEND", "log")
        backend = create_metrics_backend()
        assert isinstance(backend, LogBackend)

    def test_create_metrics_backend_from_null_env(self, monkeypatch):
        """METRICS_BACKEND=null should return NullBackend."""
        monkeypatch.setenv("METRICS_BACKEND", "null")
        backend = create_metrics_backend()
        assert isinstance(backend, NullBackend)

    def test_create_metrics_backend_from_influx_env(self, monkeypatch):
        """METRICS_BACKEND=influxdb should attempt InfluxBackend."""
        monkeypatch.setenv("METRICS_BACKEND", "influxdb")
        # Since no real InfluxDB is available, it should fall back to LogBackend
        backend = create_metrics_backend()
        # Without InfluxDB, should still return a valid backend
        assert hasattr(backend, "write_metric")
        assert hasattr(backend, "query_metric")

    def test_create_metrics_backend_unknown_env(self, monkeypatch):
        """Unknown METRICS_BACKEND value should not crash."""
        monkeypatch.setenv("METRICS_BACKEND", "unknown_backend")
        backend = create_metrics_backend()
        # Should not raise, and return something valid
        assert hasattr(backend, "write_metric")
        assert hasattr(backend, "query_metric")

    def test_create_metrics_backend_writes_and_queries(self):
        """All backends should accept write and query calls without error."""
        import os
        old = os.environ.get("METRICS_BACKEND")
        try:
            os.environ["METRICS_BACKEND"] = "null"
            backend = create_metrics_backend()
            assert backend.write_metric("test", 1.0) is True
            assert backend.query_metric("test") == []
        finally:
            if old is None:
                os.environ.pop("METRICS_BACKEND", None)
            else:
                os.environ["METRICS_BACKEND"] = old
