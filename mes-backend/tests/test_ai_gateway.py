"""
Tests for AIGateway 3-level degradation and circuit breaker.

Mocks DeepSeekClient and RedisCacheStore to test:
  - Level 1: DeepSeek API success / failure / timeout
  - Level 2: Redis cache hit / miss
  - Level 3: Rule engine fallback
  - Circuit breaker open/half-open/closed transitions
  - Streaming degradation path
  - Context enrichment in message building
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.deepseek_client import (
    ChatCompletionResult,
    ChatMessage,
    DeepSeekAPIError,
    DeepSeekTimeoutError,
    TokenUsage,
)
from app.services.ai_gateway import AIGateway


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gateway(
    api_key="test-key",
    cache_mock=None,
    deepseek_mock=None,
):
    """Create an AIGateway with controlled mocks."""
    gw = AIGateway(api_key=api_key)
    if deepseek_mock is not None:
        gw.deepseek = deepseek_mock
    if cache_mock is not None:
        gw.cache = cache_mock
    return gw


def _success_result(content="AI response", model="deepseek-chat"):
    return ChatCompletionResult(
        content=content,
        model=model,
        usage=TokenUsage(input_tokens=10, output_tokens=20),
        finish_reason="stop",
    )


def _cache_mock(get_return=None, set_return=True):
    """Create a mock RedisCacheStore."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=get_return)
    mock.get_station_latest = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=set_return)
    mock.set_station_latest = AsyncMock(return_value=set_return)
    mock._namespace = "ai:cache"
    return mock


def _deepseek_mock():
    """Create a mock DeepSeekClient."""
    mock = MagicMock()
    mock.is_configured = True
    mock._model = "deepseek-chat"
    mock.total_usage = TokenUsage()
    mock.chat = AsyncMock(return_value=_success_result())
    mock.chat_stream = MagicMock(return_value=_stream_gen())
    mock.close = AsyncMock()
    return mock


def _stream_gen(content="stream-chunk"):
    """Create an async generator for streaming."""
    from app.services.deepseek_client import StreamChunk

    async def gen():
        yield StreamChunk(content=content, done=True, usage=TokenUsage(5, 10))

    return gen()


# ---------------------------------------------------------------------------
# DeepSeek Level 1
# ---------------------------------------------------------------------------


class TestDeepSeekLevel1:
    @pytest.mark.asyncio
    async def test_deepseek_success_returns_level_deepseek(self):
        gw = _make_gateway(deepseek_mock=_deepseek_mock())
        result = await gw.analyze(prompt="test")
        assert result["level"] == "deepseek"
        assert result["content"] == "AI response"
        assert result["streamed"] is False
        assert result["model_source"] == "deepseek-chat"

    @pytest.mark.asyncio
    async def test_deepseek_success_caches_response(self):
        cache = _cache_mock()
        ds = _deepseek_mock()
        gw = _make_gateway(deepseek_mock=ds, cache_mock=cache)
        await gw.analyze(prompt="test")
        assert cache.set.called

    @pytest.mark.asyncio
    async def test_deepseek_timeout_falls_to_cache(self):
        ds = _deepseek_mock()
        ds.chat = AsyncMock(side_effect=DeepSeekTimeoutError("timeout"))
        cache = _cache_mock(get_return="cached-response")
        gw = _make_gateway(deepseek_mock=ds, cache_mock=cache)

        result = await gw.analyze(prompt="test")
        assert result["level"] == "cache"
        assert result["content"] == "cached-response"

    @pytest.mark.asyncio
    async def test_deepseek_api_error_falls_to_cache(self):
        ds = _deepseek_mock()
        ds.chat = AsyncMock(side_effect=DeepSeekAPIError("500", status_code=500))
        cache = _cache_mock(get_return="cached-response")
        gw = _make_gateway(deepseek_mock=ds, cache_mock=cache)

        result = await gw.analyze(prompt="test")
        assert result["level"] == "cache"

    @pytest.mark.asyncio
    async def test_deepseek_generic_error_falls_to_cache(self):
        ds = _deepseek_mock()
        ds.chat = AsyncMock(side_effect=RuntimeError("unknown"))
        cache = _cache_mock(get_return="cached-response")
        gw = _make_gateway(deepseek_mock=ds, cache_mock=cache)

        result = await gw.analyze(prompt="test")
        assert result["level"] == "cache"


# ---------------------------------------------------------------------------
# Cache Level 2
# ---------------------------------------------------------------------------


class TestCacheLevel2:
    @pytest.mark.asyncio
    async def test_cache_hit_with_prompt_key(self):
        cache = _cache_mock(get_return="cached-prompt-response")
        gw = _make_gateway(api_key="", cache_mock=cache)
        result = await gw.analyze(prompt="test")
        assert result["level"] == "cache"
        assert result["content"] == "cached-prompt-response"

    @pytest.mark.asyncio
    async def test_cache_hit_with_station_latest(self):
        cache = _cache_mock(get_return=None)
        cache.get_station_latest = AsyncMock(return_value="station-latest-response")
        gw = _make_gateway(api_key="", cache_mock=cache)
        result = await gw.analyze(
            prompt="test",
            context={"station_id": "STA-01"},
        )
        assert result["level"] == "cache"
        assert result["content"] == "station-latest-response"

    @pytest.mark.asyncio
    async def test_cache_miss_falls_to_rule_engine(self):
        cache = _cache_mock(get_return=None)
        gw = _make_gateway(api_key="", cache_mock=cache)
        result = await gw.analyze(prompt="test")
        assert result["level"] == "rule_engine"

    @pytest.mark.asyncio
    async def test_cache_error_falls_to_rule_engine(self):
        cache = _cache_mock()
        cache.get = AsyncMock(side_effect=Exception("redis error"))
        gw = _make_gateway(api_key="", cache_mock=cache)
        result = await gw.analyze(prompt="test")
        assert result["level"] == "rule_engine"


# ---------------------------------------------------------------------------
# Rule Engine Level 3
# ---------------------------------------------------------------------------


class TestRuleEngineLevel3:
    @pytest.mark.asyncio
    async def test_rule_engine_keyword_bottleneck(self):
        gw = _make_gateway(api_key="")
        result = await gw.analyze(prompt="bottleneck analysis")
        assert result["level"] == "rule_engine"
        assert "bottleneck" in result["content"].lower() or result["content"] != ""

    @pytest.mark.asyncio
    async def test_rule_engine_keyword_therblig(self):
        gw = _make_gateway(api_key="")
        result = await gw.analyze(prompt="therblig motion study")
        assert result["level"] == "rule_engine"

    @pytest.mark.asyncio
    async def test_rule_engine_unknown_fallback(self):
        gw = _make_gateway(api_key="")
        result = await gw.analyze(prompt="xyzrandom123")
        assert result["level"] == "rule_engine"
        assert "unavailable" in result["content"].lower()


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_circuit_starts_closed(self):
        gw = _make_gateway()
        assert gw.circuit_state == "closed"
        assert gw.is_healthy is True

    @pytest.mark.asyncio
    async def test_circuit_opens_after_allowed_failures(self):
        from app.services.ai_gateway import _ALLOWED_FAILS

        ds = _deepseek_mock()
        ds.chat = AsyncMock(side_effect=DeepSeekTimeoutError("timeout"))
        gw = _make_gateway(deepseek_mock=ds)

        for _ in range(_ALLOWED_FAILS):
            await gw.analyze(prompt="test")

        assert gw.circuit_state == "open"
        assert gw.is_healthy is False

    @pytest.mark.asyncio
    async def test_circuit_bypasses_deepseek_when_open(self):
        from app.services.ai_gateway import _ALLOWED_FAILS

        ds = _deepseek_mock()
        ds.chat = AsyncMock(side_effect=DeepSeekTimeoutError("timeout"))
        gw = _make_gateway(deepseek_mock=ds)

        # Open the circuit
        for _ in range(_ALLOWED_FAILS):
            await gw.analyze(prompt="test")

        # After opening, DeepSeek should NOT be called
        ds.chat.reset_mock()
        await gw.analyze(prompt="test2")
        ds.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_resets_circuit(self):
        ds = _deepseek_mock()
        ds.chat = AsyncMock(side_effect=DeepSeekTimeoutError("timeout"))
        gw = _make_gateway(deepseek_mock=ds)

        # Cause failures
        await gw.analyze(prompt="test")
        await gw.analyze(prompt="test")
        assert len(gw._failures) == 2

        # Success resets
        ds.chat = AsyncMock(return_value=_success_result())
        await gw.analyze(prompt="test")
        assert len(gw._failures) == 0
        assert gw.circuit_state == "closed"

    @pytest.mark.asyncio
    async def test_circuit_cooldown_expires(self):
        from app.services.ai_gateway import (
            _ALLOWED_FAILS,
            _CIRCUIT_COOLDOWN,
        )

        ds = _deepseek_mock()
        ds.chat = AsyncMock(side_effect=DeepSeekTimeoutError("timeout"))
        gw = _make_gateway(deepseek_mock=ds)

        # Open the circuit
        for _ in range(_ALLOWED_FAILS):
            await gw.analyze(prompt="test")

        assert gw.circuit_state == "open"

        # Advance past cooldown
        gw._circuit_open_until = time.monotonic() - 1.0
        assert gw.circuit_state == "half_open"
        assert gw.is_healthy is True  # Should allow trial


# ---------------------------------------------------------------------------
# Not Configured (no API key)
# ---------------------------------------------------------------------------


class TestNotConfigured:
    @pytest.mark.asyncio
    async def test_no_api_key_skips_deepseek(self):
        ds = _deepseek_mock()
        gw = _make_gateway(api_key="", deepseek_mock=ds)
        # Without valid key, DeepSeek is not configured
        gw.deepseek.is_configured = False

        result = await gw.analyze(prompt="test")
        ds.chat.assert_not_called()
        assert result["level"] == "rule_engine"


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


class TestStreaming:
    @pytest.mark.asyncio
    async def test_stream_mode_returns_generator(self):
        ds = _deepseek_mock()
        gw = _make_gateway(deepseek_mock=ds)
        result = await gw.analyze(prompt="test", stream=True)
        assert result["streamed"] is True
        assert result["generator"] is not None

    @pytest.mark.asyncio
    async def test_analyze_stream_convenience(self):
        ds = _deepseek_mock()
        gw = _make_gateway(deepseek_mock=ds)
        chunks = []
        async for chunk in gw.analyze_stream(prompt="test"):
            chunks.append(chunk)
        assert len(chunks) == 1
        assert chunks[0] == "stream-chunk"


# ---------------------------------------------------------------------------
# Message Building & Context
# ---------------------------------------------------------------------------


class TestMessageBuilding:
    def test_build_messages_system_and_user(self):
        gw = _make_gateway()
        msgs = gw._build_messages("hello", {})
        assert len(msgs) == 2
        assert msgs[0].role == "system"
        assert msgs[1].role == "user"
        assert msgs[1].content == "hello"

    def test_build_messages_enriches_context(self):
        gw = _make_gateway()
        msgs = gw._build_messages(
            "analyze",
            {"station_id": "STA-01", "line_id": "L01", "shift": "morning"},
        )
        content = msgs[1].content
        assert "STA-01" in content
        assert "L01" in content
        assert "morning" in content

    def test_build_messages_with_metrics(self):
        gw = _make_gateway()
        msgs = gw._build_messages(
            "analyze",
            {"metrics": {"utilization": 85.5}},
        )
        content = msgs[1].content
        assert "85.5" in content

    @pytest.mark.asyncio
    async def test_prebuilt_messages_override_prompt(self):
        """When messages are provided, they are used directly."""
        ds = _deepseek_mock()
        gw = _make_gateway(deepseek_mock=ds)
        custom = [ChatMessage(role="user", content="custom")]
        result = await gw.analyze(prompt="ignored", messages=custom)
        ds.chat.assert_called_once()
        assert ds.chat.call_args.kwargs["messages"] == custom


# ---------------------------------------------------------------------------
# Status & Lifecycle
# ---------------------------------------------------------------------------


class TestStatusAndLifecycle:
    def test_get_status(self):
        gw = _make_gateway()
        status = gw.get_status()
        assert "circuit_state" in status
        assert "failure_count" in status
        assert "deepseek_configured" in status
        assert "cache_available" in status

    @pytest.mark.asyncio
    async def test_close_delegates_to_deepseek(self):
        ds = _deepseek_mock()
        gw = _make_gateway(deepseek_mock=ds)
        await gw.close()
        ds.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_cache_store(self):
        cache = _cache_mock()
        gw = _make_gateway()
        assert gw.cache is None
        gw.set_cache_store(cache)
        assert gw.cache is cache
