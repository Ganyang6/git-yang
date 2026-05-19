"""
Redis-based AI response cache store.

Provides caching layer for AI gateway degradation (Level 2 fallback).
Supports per-station caching, TTL management, and cache hit statistics.

Cache key design:
  - ai:cache:{prompt_hash}          - Generic query cache (30 min TTL)
  - ai:cache:station:{station_id}:latest - Latest result per station (5 min TTL)

Reference: spec_phase4_celery_ai_onnx.md Section 3.4
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Default TTL values (seconds)
_TTL_ANALYSIS = 1800   # 30 minutes for analysis results
_TTL_KPI = 300         # 5 minutes for KPI data
_TTL_STATION = 300     # 5 minutes for per-station latest
_TTL_DEFAULT = 600     # 10 minutes default


@dataclass
class CacheStats:
    """Cache hit/miss statistics."""

    hits: int = 0
    misses: int = 0
    sets: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "hit_rate": round(self.hit_rate, 4),
        }


class RedisCacheStore:
    """Redis-backed cache for AI responses.

    Wraps redis.asyncio client with AI-specific caching semantics:
    - TTL-based expiry per cache type
    - Prompt hash-based deduplication
    - Per-station latest result caching
    - Hit/miss statistics for monitoring

    Usage:
        store = RedisCacheStore(redis_pool)
        await store.set("ai:cache:abc123", "response text", ttl=1800)
        result = await store.get("ai:cache:abc123")
    """

    def __init__(self, redis_client=None, namespace: str = "ai:cache"):
        """Initialize cache store.

        Args:
            redis_client: redis.asyncio.Redis client instance.
            namespace: Key prefix namespace.
        """
        self._redis = redis_client
        self._namespace = namespace
        self._stats = CacheStats()

    @property
    def is_available(self) -> bool:
        return self._redis is not None

    @property
    def stats(self) -> CacheStats:
        return self._stats

    @staticmethod
    def make_key(prompt: str, namespace: str = "ai:cache") -> str:
        """Generate a cache key from prompt text.

        Uses SHA-256 hash truncated to 16 chars for short keys.
        """
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        return f"{namespace}:{prompt_hash}"

    @staticmethod
    def make_station_key(station_id: str, namespace: str = "ai:cache") -> str:
        """Generate a per-station cache key for latest analysis result."""
        return f"{namespace}:station:{station_id}:latest"

    async def get(self, key: str) -> Optional[str]:
        """Get a cached value by key.

        Returns the cached string, or None if not found.
        Updates hit/miss statistics.
        """
        if self._redis is None:
            self._stats.misses += 1
            return None

        try:
            val = await self._redis.get(key)
            if val is not None:
                self._stats.hits += 1
                logger.debug("Cache hit: %s", key)
                return val if isinstance(val, str) else val.decode("utf-8")
            self._stats.misses += 1
            return None
        except Exception as exc:
            self._stats.misses += 1
            logger.warning("Cache get error for %s: %s", key, exc)
            return None

    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None,
    ) -> bool:
        """Set a cached value with optional TTL.

        Args:
            key: Cache key.
            value: String value to cache.
            ttl: Time-to-live in seconds. Uses _TTL_DEFAULT if not specified.

        Returns True if set succeeded.
        """
        if self._redis is None:
            return False

        try:
            await self._redis.setex(key, ttl or _TTL_DEFAULT, value)
            self._stats.sets += 1
            logger.debug("Cache set: %s (TTL=%ds)", key, ttl or _TTL_DEFAULT)
            return True
        except Exception as exc:
            logger.warning("Cache set error for %s: %s", key, exc)
            return False

    async def delete(self, key: str) -> bool:
        """Delete a cached value."""
        if self._redis is None:
            return False

        try:
            await self._redis.delete(key)
            return True
        except Exception as exc:
            logger.warning("Cache delete error for %s: %s", key, exc)
            return False

    async def exists(self, key: str) -> bool:
        """Check if a key exists in cache."""
        if self._redis is None:
            return False

        try:
            return bool(await self._redis.exists(key))
        except Exception:
            return False

    async def get_analysis(self, prompt: str) -> Optional[str]:
        """Get cached analysis result by prompt text.

        Uses 30-minute TTL.
        """
        key = self.make_key(prompt, self._namespace)
        return await self.get(key)

    async def set_analysis(self, prompt: str, result: str) -> bool:
        """Cache an analysis result by prompt text.

        Uses 30-minute TTL.
        """
        key = self.make_key(prompt, self._namespace)
        return await self.set(key, result, ttl=_TTL_ANALYSIS)

    async def get_station_latest(self, station_id: str) -> Optional[str]:
        """Get the latest cached analysis for a station.

        Uses 5-minute TTL.
        """
        key = self.make_station_key(station_id, self._namespace)
        return await self.get(key)

    async def set_station_latest(
        self, station_id: str, result: str
    ) -> bool:
        """Cache the latest analysis result for a station.

        Uses 5-minute TTL.
        """
        key = self.make_station_key(station_id, self._namespace)
        return await self.set(key, result, ttl=_TTL_STATION)

    async def get_kpi(self, key_suffix: str) -> Optional[str]:
        """Get cached KPI data.

        Uses 5-minute TTL.
        """
        key = f"{self._namespace}:kpi:{key_suffix}"
        return await self.get(key)

    async def set_kpi(self, key_suffix: str, data: str) -> bool:
        """Cache KPI data.

        Uses 5-minute TTL.
        """
        key = f"{self._namespace}:kpi:{key_suffix}"
        return await self.set(key, data, ttl=_TTL_KPI)

    async def clear_expired_results(self) -> int:
        """Clean up expired analysis results.

        This is a no-op since Redis handles TTL natively.
        Kept for interface compatibility with scheduled cleanup tasks.

        Returns 0 (no manual cleanup needed with Redis TTL).
        """
        logger.debug("Redis TTL handles expiry automatically, no manual cleanup")
        return 0

    async def get_stats_summary(self) -> dict:
        """Return cache statistics summary."""
        return {
            "stats": self._stats.to_dict(),
            "available": self.is_available,
            "namespace": self._namespace,
        }
