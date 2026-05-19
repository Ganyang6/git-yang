"""Action anomaly detector for MES backend.

Detects anomalies in real-time action events by comparing
duration against historical baselines per station+action.

Detection method:
  - Maintain rolling mean and std for each (station_id, action) pair
  - Flag segments where duration deviates > N * std from mean
  - Requires minimum sample count (default 10) before enabling detection
    to avoid cold-start false positives

Anomaly events are written to InfluxDB and published to Redis Pub/Sub.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("mes_backend.anomaly_detector")


@dataclass
class AnomalyEvent:
    """Represents a detected anomaly in action execution."""

    station_id: str
    action: str
    anomaly_type: str  # "duration_deviation"
    duration_ms: float
    mean_duration: float
    std_duration: float
    deviation_sigma: float
    timestamp: float
    id: str = ""


@dataclass
class _ActionStats:
    """Rolling statistics for a single (station_id, action) pair.

    Uses Welford's online algorithm for numerically stable variance
    computation (P1 #51).
    """

    count: int = 0
    mean_duration: float = 0.0  # Welford running mean
    m2: float = 0.0  # Welford sum of squared deviations from mean
    min_duration: float = float("inf")
    max_duration: float = 0.0
    _total_duration: float = 0.0  # kept for decay compatibility

    @property
    def mean(self) -> float:
        return self.mean_duration

    @property
    def variance(self) -> float:
        if self.count < 2:
            return 0.0
        return max(0.0, self.m2 / (self.count - 1))

    @property
    def std(self) -> float:
        return self.variance ** 0.5

    def update(self, duration_ms: float) -> None:
        # Welford's online algorithm for numerically stable variance
        self.count += 1
        delta = duration_ms - self.mean_duration
        self.mean_duration += delta / self.count
        delta2 = duration_ms - self.mean_duration
        self.m2 += delta * delta2
        self._total_duration += duration_ms
        self.min_duration = min(self.min_duration, duration_ms)
        self.max_duration = max(self.max_duration, duration_ms)

    def decay(self, factor: float = 0.9) -> None:
        """Decay statistics by a factor to gradually forget old data.

        Uses exponential decay to prevent hard reset when max_history is
        reached, avoiding detection blind spots (P1 #50).
        """
        if self.count == 0:
            return
        self._total_duration *= factor
        self.m2 *= factor
        self.count = max(1, int(self.count * factor))


class AnomalyDetector:
    """Detects action duration anomalies using statistical analysis.

    Usage:
        detector = AnomalyDetector(sigma_threshold=2.0, min_samples=10)
        anomaly = detector.check(station_id="ws_01", action="reach", duration_ms=5000)
    """

    def __init__(
        self,
        sigma_threshold: float = 2.0,
        min_samples: int = 10,
        max_history_per_key: int = 1000,
    ) -> None:
        self._sigma_threshold = sigma_threshold
        self._min_samples = min_samples
        self._max_history = max_history_per_key
        self._stats: Dict[Tuple[str, str], _ActionStats] = defaultdict(_ActionStats)
        self._lock = threading.Lock()
        self._anomaly_count: int = 0
        self._total_checked: int = 0

    def check(
        self,
        station_id: str,
        action: str,
        duration_ms: float,
        timestamp: float | None = None,
    ) -> Optional[AnomalyEvent]:
        """Check if an action duration is anomalous.

        Args:
            station_id: Work station identifier.
            action: Action label (e.g. "reach", "assemble").
            duration_ms: Duration of the action segment in milliseconds.
            timestamp: Epoch timestamp (defaults to now).

        Returns:
            AnomalyEvent if anomaly detected, None otherwise.
        """
        key = (station_id, action)
        with self._lock:
            stats = self._stats[key]
            self._total_checked += 1

            if timestamp is None:
                timestamp = time.time()

            # Check for anomaly BEFORE updating stats (to avoid self-fulfilling)
            anomaly = None
            if stats.count >= self._min_samples and stats.std > 0:
                deviation = abs(duration_ms - stats.mean)
                sigma = deviation / stats.std

                if sigma >= self._sigma_threshold:
                    anomaly = AnomalyEvent(
                        station_id=station_id,
                        action=action,
                        anomaly_type="duration_deviation",
                        duration_ms=duration_ms,
                        mean_duration=stats.mean,
                        std_duration=stats.std,
                        deviation_sigma=sigma,
                        timestamp=timestamp,
                        id=f"anomaly_{station_id}_{action}_{int(timestamp * 1000)}",
                    )
                    self._anomaly_count += 1
                    logger.info(
                        "Anomaly detected: station=%s action=%s duration=%.0fms "
                        "mean=%.0fms std=%.0fms sigma=%.1f",
                        station_id, action, duration_ms,
                        stats.mean, stats.std, sigma,
                    )

            # Always update stats for learning
            stats.update(duration_ms)

            # Cap history size using decay instead of hard reset (P1 #50)
            if stats.count > self._max_history:
                stats.decay(factor=0.5)

        return anomaly

    def get_stats(self, station_id: str, action: str) -> Dict[str, Any]:
        """Get current statistics for a station+action pair."""
        key = (station_id, action)
        with self._lock:
            stats = self._stats[key]
            return {
                "station_id": station_id,
                "action": action,
                "count": stats.count,
                "mean_duration": round(stats.mean, 2),
                "std_duration": round(stats.std, 2),
                "min_duration": round(stats.min_duration, 2) if stats.min_duration != float("inf") else 0,
                "max_duration": round(stats.max_duration, 2),
                "is_ready": stats.count >= self._min_samples,
            }

    @property
    def anomaly_count(self) -> int:
        return self._anomaly_count

    @property
    def total_checked(self) -> int:
        return self._total_checked

    def reset(self) -> None:
        """Reset all learned statistics."""
        with self._lock:
            self._stats.clear()
            self._anomaly_count = 0
            self._total_checked = 0
