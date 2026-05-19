"""
Tests for RedisCacheStore.

Mocks redis.asyncio client to test cache semantics without a real Redis.
Covers: get/set/delete/exists, TTL, prompt hashing, station caching,
        stats tracking, error handling, and KPI convenience methods.
"""

import hashlib

import pytest

from app.services.cache_store import CacheStats, RedisCacheStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(redis_mock=None, namespace="ai:cache"):
    return RedisCacheStore(redis_client=redis_mock, namespace=namespace)


class AsyncMock:
    """Minimal async mock for redis methods."""

    def __init__(self, return_value=None, side_effect=None):
        self.return_value = return_value
        self.side_effect = side_effect
        self.calls = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.side_effect:
            raise self.side_effect
        return self.return_value


# ---------------------------------------------------------------------------
# CacheStats
# ---------------------------------------------------------------------------


class TestCacheStats:
    def test_hit_rate_zero_when_no_data(self):
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate_with_data(self):
        stats = CacheStats(hits=8, misses=2)
        assert stats.hit_rate == 0.8

    def test_to_dict(self):
        stats = CacheStats(hits=3, misses=1, sets=5)
        d = stats.to_dict()
        assert d["hits"] == 3
        assert d["misses"] == 1
        assert d["sets"] == 5
        assert "hit_rate" in d


# ---------------------------------------------------------------------------
# make_key / make_station_key (static)
# ---------------------------------------------------------------------------


class TestKeyGeneration:
    def test_make_key_produces_sha256_prefix(self):
        key = RedisCacheStore.make_key("hello world", "ns")
        assert key.startswith("ns:")
        suffix = key[3:]
        # SHA-256 hex truncated to 16 chars
        expected = hashlib.sha256(b"hello world").hexdigest()[:16]
        assert suffix == expected

    def test_make_key_different_prompts_different_keys(self):
        k1 = RedisCacheStore.make_key("prompt A", "ns")
        k2 = RedisCacheStore.make_key("prompt B", "ns")
        assert k1 != k2

    def test_make_key_same_prompt_same_key(self):
        k1 = RedisCacheStore.make_key("test", "ns")
        k2 = RedisCacheStore.make_key("test", "ns")
        assert k1 == k2

    def test_make_station_key(self):
        key = RedisCacheStore.make_station_key("STA-01", "ns")
        assert key == "ns:station:STA-01:latest"


# ---------------------------------------------------------------------------
# RedisCacheStore -- no redis (degraded mode)
# ---------------------------------------------------------------------------


class TestCacheStoreNoRedis:
    def test_is_available_false(self):
        store = _make_store(redis_mock=None)
        assert store.is_available is False

    @pytest.mark.asyncio
    async def test_get_returns_none_and_increments_miss(self):
        store = _make_store(redis_mock=None)
        result = await store.get("any-key")
        assert result is None
        assert store.stats.misses == 1

    @pytest.mark.asyncio
    async def test_set_returns_false(self):
        store = _make_store(redis_mock=None)
        assert await store.set("k", "v") is False

    @pytest.mark.asyncio
    async def test_delete_returns_false(self):
        store = _make_store(redis_mock=None)
        assert await store.delete("k") is False

    @pytest.mark.asyncio
    async def test_exists_returns_false(self):
        store = _make_store(redis_mock=None)
        assert await store.exists("k") is False


# ---------------------------------------------------------------------------
# RedisCacheStore -- with mock redis
# ---------------------------------------------------------------------------


class TestCacheStoreWithRedis:
    @pytest.mark.asyncio
    async def test_get_hit(self):
        mock_redis = type("MockRedis", (), {
            "get": AsyncMock(return_value=b"cached-value"),
        })()
        store = _make_store(redis_mock=mock_redis)
        result = await store.get("k")
        assert result == "cached-value"
        assert store.stats.hits == 1

    @pytest.mark.asyncio
    async def test_get_miss(self):
        mock_redis = type("MockRedis", (), {
            "get": AsyncMock(return_value=None),
        })()
        store = _make_store(redis_mock=mock_redis)
        result = await store.get("k")
        assert result is None
        assert store.stats.misses == 1

    @pytest.mark.asyncio
    async def test_get_string_value(self):
        """redis returns str when decode_responses=True."""
        mock_redis = type("MockRedis", (), {
            "get": AsyncMock(return_value="string-value"),
        })()
        store = _make_store(redis_mock=mock_redis)
        result = await store.get("k")
        assert result == "string-value"

    @pytest.mark.asyncio
    async def test_get_error_treated_as_miss(self):
        mock_redis = type("MockRedis", (), {
            "get": AsyncMock(side_effect=ConnectionError("Redis down")),
        })()
        store = _make_store(redis_mock=mock_redis)
        result = await store.get("k")
        assert result is None
        assert store.stats.misses == 1

    @pytest.mark.asyncio
    async def test_set_success(self):
        mock_redis = type("MockRedis", (), {
            "setex": AsyncMock(return_value=True),
        })()
        store = _make_store(redis_mock=mock_redis)
        assert await store.set("k", "v", ttl=300) is True
        assert store.stats.sets == 1
        call_args = mock_redis.setex.calls[0][0]
        assert call_args[0] == "k"
        assert call_args[1] == 300
        assert call_args[2] == "v"

    @pytest.mark.asyncio
    async def test_set_default_ttl(self):
        """When ttl is None, uses _TTL_DEFAULT (600s)."""
        mock_redis = type("MockRedis", (), {
            "setex": AsyncMock(return_value=True),
        })()
        store = _make_store(redis_mock=mock_redis)
        await store.set("k", "v")
        call_args = mock_redis.setex.calls[0][0]
        assert call_args[1] == 600  # _TTL_DEFAULT

    @pytest.mark.asyncio
    async def test_set_error_returns_false(self):
        mock_redis = type("MockRedis", (), {
            "setex": AsyncMock(side_effect=Exception("write fail")),
        })()
        store = _make_store(redis_mock=mock_redis)
        assert await store.set("k", "v") is False

    @pytest.mark.asyncio
    async def test_delete_success(self):
        mock_redis = type("MockRedis", (), {
            "delete": AsyncMock(return_value=1),
        })()
        store = _make_store(redis_mock=mock_redis)
        assert await store.delete("k") is True

    @pytest.mark.asyncio
    async def test_delete_error_returns_false(self):
        mock_redis = type("MockRedis", (), {
            "delete": AsyncMock(side_effect=Exception("del fail")),
        })()
        store = _make_store(redis_mock=mock_redis)
        assert await store.delete("k") is False

    @pytest.mark.asyncio
    async def test_exists_true(self):
        mock_redis = type("MockRedis", (), {
            "exists": AsyncMock(return_value=1),
        })()
        store = _make_store(redis_mock=mock_redis)
        assert await store.exists("k") is True

    @pytest.mark.asyncio
    async def test_exists_false(self):
        mock_redis = type("MockRedis", (), {
            "exists": AsyncMock(return_value=0),
        })()
        store = _make_store(redis_mock=mock_redis)
        assert await store.exists("k") is False

    @pytest.mark.asyncio
    async def test_exists_error_returns_false(self):
        mock_redis = type("MockRedis", (), {
            "exists": AsyncMock(side_effect=Exception("err")),
        })()
        store = _make_store(redis_mock=mock_redis)
        assert await store.exists("k") is False


# ---------------------------------------------------------------------------
# Convenience methods: analysis, station, kpi
# ---------------------------------------------------------------------------


class TestCacheStoreConvenienceMethods:
    @pytest.mark.asyncio
    async def test_get_analysis_calls_get_with_correct_key(self):
        mock_redis = type("MockRedis", (), {
            "get": AsyncMock(return_value="analysis result"),
        })()
        store = _make_store(redis_mock=mock_redis)
        result = await store.get_analysis("Analyze station STA-01")
        assert result == "analysis result"
        key = RedisCacheStore.make_key("Analyze station STA-01", "ai:cache")
        assert mock_redis.get.calls[0][0][0] == key

    @pytest.mark.asyncio
    async def test_set_analysis_uses_30_min_ttl(self):
        mock_redis = type("MockRedis", (), {
            "setex": AsyncMock(return_value=True),
        })()
        store = _make_store(redis_mock=mock_redis)
        await store.set_analysis("prompt", "result")
        ttl = mock_redis.setex.calls[0][0][1]
        assert ttl == 1800  # _TTL_ANALYSIS

    @pytest.mark.asyncio
    async def test_station_latest_get_set(self):
        mock_redis = type("MockRedis", (), {
            "get": AsyncMock(return_value="latest analysis"),
            "setex": AsyncMock(return_value=True),
        })()
        store = _make_store(redis_mock=mock_redis)
        got = await store.get_station_latest("STA-01")
        assert got == "latest analysis"
        assert await store.set_station_latest("STA-01", "new result") is True
        # set uses _TTL_STATION (300)
        ttl = mock_redis.setex.calls[0][0][1]
        assert ttl == 300

    @pytest.mark.asyncio
    async def test_kpi_get_set(self):
        mock_redis = type("MockRedis", (), {
            "get": AsyncMock(return_value="kpi-data"),
            "setex": AsyncMock(return_value=True),
        })()
        store = _make_store(redis_mock=mock_redis)
        got = await store.get_kpi("utilization")
        assert got == "kpi-data"
        assert await store.set_kpi("utilization", "85.2") is True
        # Key should be namespace:kpi:utilization
        key = mock_redis.setex.calls[0][0][0]
        assert key == "ai:cache:kpi:utilization"
        ttl = mock_redis.setex.calls[0][0][1]
        assert ttl == 300  # _TTL_KPI


# ---------------------------------------------------------------------------
# clear_expired_results / get_stats_summary
# ---------------------------------------------------------------------------


class TestCacheStoreMaintenance:
    @pytest.mark.asyncio
    async def test_clear_expired_returns_zero(self):
        """Redis TTL handles expiry; this is a no-op."""
        store = _make_store(redis_mock=None)
        assert await store.clear_expired_results() == 0

    @pytest.mark.asyncio
    async def test_get_stats_summary(self):
        mock_redis = type("MockRedis", (), {
            "get": AsyncMock(return_value=None),
        })()
        store = _make_store(redis_mock=mock_redis, namespace="test")
        await store.get("k1")  # miss
        summary = await store.get_stats_summary()
        assert summary["stats"]["misses"] == 1
        assert summary["available"] is True
        assert summary["namespace"] == "test"
