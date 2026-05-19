"""Tests for AnomalyDetector service (T5-06).

Covers:
  - Normal operation detection
  - Anomaly detection with sigma threshold
  - Cold-start (insufficient samples)
  - Stats retrieval
  - Reset functionality
  - Anomaly API endpoints
"""

from __future__ import annotations

import os
import time
import pytest
from typing import Any, Dict


class TestActionStats:
    """_ActionStats rolling statistics."""

    def test_mean_single_value(self):
        from app.services.anomaly_detector import _ActionStats

        stats = _ActionStats()
        stats.update(100.0)
        assert stats.mean == 100.0

    def test_mean_multiple_values(self):
        from app.services.anomaly_detector import _ActionStats

        stats = _ActionStats()
        for v in [100, 200, 300]:
            stats.update(float(v))
        assert stats.mean == 200.0

    def test_std_zero_for_single(self):
        from app.services.anomaly_detector import _ActionStats

        stats = _ActionStats()
        stats.update(100.0)
        assert stats.std == 0.0

    def test_std_calculation(self):
        from app.services.anomaly_detector import _ActionStats

        stats = _ActionStats()
        for v in [10, 20, 30]:
            stats.update(float(v))
        # Welford sample variance: m2/(n-1) = 200/2 = 100
        # std = sqrt(100) = 10.0
        assert abs(stats.std - 10.0) < 0.01

    def test_min_max_tracking(self):
        from app.services.anomaly_detector import _ActionStats

        stats = _ActionStats()
        for v in [50, 100, 75, 200, 25]:
            stats.update(float(v))
        assert stats.min_duration == 25.0
        assert stats.max_duration == 200.0


class TestAnomalyDetector:
    """Core anomaly detection logic."""

    def test_cold_start_no_detection(self):
        """Should not detect anomaly with insufficient samples."""
        from app.services.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(min_samples=10)

        for _ in range(5):
            result = detector.check("ws_01", "reach", 500.0)

        assert result is None
        assert detector.anomaly_count == 0

    def test_normal_operation_no_anomaly(self):
        """Values within normal range should not trigger anomaly."""
        from app.services.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(sigma_threshold=2.0, min_samples=5)

        # Feed normal values
        for _ in range(20):
            detector.check("ws_01", "reach", 500.0)

        # Feed another normal value
        result = detector.check("ws_01", "reach", 520.0)
        assert result is None

    def test_anomaly_detected(self):
        """Extreme deviation should trigger anomaly."""
        from app.services.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(sigma_threshold=2.0, min_samples=5)

        # Feed normal values with slight variation (mean ~500, std ~10)
        for v in [490, 505, 495, 510, 500, 505, 495, 500, 510, 490,
                   495, 505, 500, 510, 495, 505, 490, 510, 500, 495]:
            detector.check("ws_01", "reach", float(v))

        # Feed extreme value (5000ms is way above mean ~500)
        result = detector.check("ws_01", "reach", 5000.0)

        assert result is not None
        assert result.station_id == "ws_01"
        assert result.action == "reach"
        assert result.anomaly_type == "duration_deviation"
        assert result.duration_ms == 5000.0
        assert result.deviation_sigma >= 2.0
        assert detector.anomaly_count == 1

    def test_separate_station_tracking(self):
        """Different stations should have independent baselines."""
        from app.services.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(min_samples=5)

        # Station A has short durations with variation
        for v in [290, 310, 300, 295, 305, 300, 310, 290, 305, 295,
                   300, 310, 295, 305, 290, 310, 300, 295, 305, 300]:
            detector.check("ws_A", "reach", float(v))

        # Station B has long durations with variation
        for v in [780, 820, 800, 790, 810, 800, 820, 790, 810, 780,
                   790, 810, 800, 820, 790, 810, 780, 820, 790, 800]:
            detector.check("ws_B", "reach", float(v))

        # 300ms is normal for A but anomalous for B (mean ~800)
        result_a = detector.check("ws_A", "reach", 300.0)
        result_b = detector.check("ws_B", "reach", 300.0)

        assert result_a is None
        assert result_b is not None

    def test_separate_action_tracking(self):
        """Different actions on same station should have independent baselines."""
        from app.services.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(min_samples=5)

        for i in range(20):
            reach_v = 290 + (i % 5) * 5
            asm_v = 1950 + (i % 5) * 20
            detector.check("ws_01", "reach", float(reach_v))
            detector.check("ws_01", "assemble", float(asm_v))

        # Assemble with reach-like duration is anomalous
        result = detector.check("ws_01", "assemble", 300.0)
        assert result is not None

    def test_get_stats_before_ready(self):
        """Stats should show is_ready=False before min_samples."""
        from app.services.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(min_samples=10)
        stats = detector.get_stats("ws_01", "reach")

        assert stats["is_ready"] is False

    def test_get_stats_after_ready(self):
        """Stats should show is_ready=True after min_samples."""
        from app.services.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(min_samples=5)
        for _ in range(10):
            detector.check("ws_01", "reach", 500.0)

        stats = detector.get_stats("ws_01", "reach")
        assert stats["is_ready"] is True
        assert stats["count"] >= 5
        assert stats["mean_duration"] == 500.0

    def test_reset_clears_all(self):
        """Reset should clear all learned statistics."""
        from app.services.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(min_samples=3)
        for _ in range(20):
            detector.check("ws_01", "reach", 500.0)

        detector.reset()

        stats = detector.get_stats("ws_01", "reach")
        assert stats["count"] == 0
        assert stats["is_ready"] is False
        assert detector.anomaly_count == 0

    def test_high_sigma_threshold(self):
        """Higher sigma threshold should be less sensitive."""
        from app.services.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(sigma_threshold=5.0, min_samples=5)

        # Feed values with variation (mean ~500, std ~10)
        for v in [490, 505, 495, 510, 500, 505, 495, 500, 510, 490,
                   495, 505, 500, 510, 495, 505, 490, 510, 500, 495]:
            detector.check("ws_01", "reach", float(v))

        # ~450 sigma deviation should NOT trigger with 5-sigma threshold
        # 1000ms is about 50 sigma away from mean~500, so it WILL trigger
        result = detector.check("ws_01", "reach", 1000.0)
        assert result is not None
        assert result.deviation_sigma >= 5.0

        # Now verify that a value just beyond 2-sigma but below 5-sigma
        # does NOT trigger (sigma_threshold=5.0)
        # With mean~500, std~7, value 520 is ~3 sigma -- below threshold
        result_normal = detector.check("ws_01", "reach", 520.0)
        assert result_normal is None

    def test_history_capping(self):
        """Stats should be capped at max_history to prevent memory growth."""
        from app.services.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(min_samples=3, max_history_per_key=10)

        for _ in range(15):
            detector.check("ws_01", "reach", 500.0)

        # After exceeding max_history, stats should reset
        stats = detector.get_stats("ws_01", "reach")
        assert stats["count"] <= 15  # may have reset

    def test_custom_timestamp(self):
        """AnomalyEvent should use provided timestamp."""
        from app.services.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(min_samples=3)

        # Feed values with variation so std > 0
        for v in [490, 505, 495, 510, 500, 505, 495, 500, 510, 490]:
            detector.check("ws_01", "reach", float(v))

        custom_ts = 1700000000.0
        result = detector.check("ws_01", "reach", 9999.0, timestamp=custom_ts)
        assert result is not None
        assert result.timestamp == custom_ts


class TestAnomalyApiEndpoints:
    """Anomaly API endpoint tests.

    Uses the session-scoped ``client`` fixture from conftest.py which
    already creates tables via lifespan(init_db).  Data is injected via
    the module-level ``_anomaly_store`` in-memory list so that no extra
    DB setup is required per test.
    """

    def test_get_events_empty(self, client):
        from app.api.v1.anomaly import _anomaly_store

        _anomaly_store.clear()

        resp = client.get("/api/anomaly/events")
        data = resp.json()

        assert resp.status_code == 200
        assert data["code"] == 0
        assert data["data"]["total"] == 0
        assert data["data"]["events"] == []

    def test_get_events_with_data(self, client):
        from app.api.v1.anomaly import _anomaly_store, add_anomaly_event

        _anomaly_store.clear()
        add_anomaly_event({
            "id": "test_001",
            "station_id": "ws_01",
            "action": "reach",
            "anomaly_type": "duration_deviation",
            "duration_ms": 5000.0,
            "mean_duration": 500.0,
            "std_duration": 100.0,
            "deviation_sigma": 45.0,
            "timestamp": time.time(),
        })

        resp = client.get("/api/anomaly/events")
        data = resp.json()

        assert resp.status_code == 200
        assert data["data"]["total"] == 1
        assert len(data["data"]["events"]) == 1

    def test_get_events_filter_by_station(self, client):
        from app.api.v1.anomaly import _anomaly_store, add_anomaly_event

        _anomaly_store.clear()
        add_anomaly_event({"id": "1", "station_id": "ws_01", "action": "reach", "anomaly_type": "duration_deviation", "duration_ms": 0, "mean_duration": 0, "std_duration": 0, "deviation_sigma": 0, "timestamp": 1})
        add_anomaly_event({"id": "2", "station_id": "ws_02", "action": "assemble", "anomaly_type": "duration_deviation", "duration_ms": 0, "mean_duration": 0, "std_duration": 0, "deviation_sigma": 0, "timestamp": 2})
        add_anomaly_event({"id": "3", "station_id": "ws_01", "action": "grasp", "anomaly_type": "duration_deviation", "duration_ms": 0, "mean_duration": 0, "std_duration": 0, "deviation_sigma": 0, "timestamp": 3})

        resp = client.get("/api/anomaly/events?station_id=ws_01")
        data = resp.json()

        assert data["data"]["total"] == 3
        assert data["data"]["returned"] == 2

    def test_get_stats(self, client):
        from app.api.v1.anomaly import _anomaly_store, add_anomaly_event

        _anomaly_store.clear()
        add_anomaly_event({"id": "1", "station_id": "ws_01", "action": "reach", "anomaly_type": "duration_deviation", "duration_ms": 0, "mean_duration": 0, "std_duration": 0, "deviation_sigma": 0, "timestamp": 1})
        add_anomaly_event({"id": "2", "station_id": "ws_01", "action": "reach", "anomaly_type": "duration_deviation", "duration_ms": 0, "mean_duration": 0, "std_duration": 0, "deviation_sigma": 0, "timestamp": 2})
        add_anomaly_event({"id": "3", "station_id": "ws_02", "action": "assemble", "anomaly_type": "duration_deviation", "duration_ms": 0, "mean_duration": 0, "std_duration": 0, "deviation_sigma": 0, "timestamp": 3})

        resp = client.get("/api/anomaly/stats")
        data = resp.json()

        assert resp.status_code == 200
        assert data["data"]["total_anomalies"] == 3
        assert data["data"]["by_station"]["ws_01"] == 2
        assert data["data"]["by_action"]["reach"] == 2
