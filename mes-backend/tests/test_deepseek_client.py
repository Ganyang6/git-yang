"""
Tests for DeepSeekClient.

Mocks httpx to test:
  - Successful chat completion parsing
  - Token usage tracking
  - Retry on transient errors (timeout, 5xx, 429)
  - No retry on 4xx client errors
  - Streaming response parsing
  - is_configured / close behavior
  - Headers and payload construction
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.deepseek_client import (
    ChatCompletionResult,
    ChatMessage,
    DeepSeekAPIError,
    DeepSeekTimeoutError,
    DeepSeekClient,
    StreamChunk,
    TokenUsage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    api_key="test-key",
    max_retries=3,
    timeout=5,
):
    return DeepSeekClient(
        api_key=api_key,
        api_url="https://api.deepseek.com/v1/chat/completions",
        model="deepseek-chat",
        timeout=timeout,
        max_retries=max_retries,
    )


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.is_closed = False
    return resp


def _success_json(content="response", model="deepseek-chat", finish="stop"):
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        "model": model,
    }


# ---------------------------------------------------------------------------
# Basic Properties
# ---------------------------------------------------------------------------


class TestDeepSeekClientBasics:
    def test_is_configured_true_with_valid_key(self):
        client = _make_client(api_key="sk-123")
        assert client.is_configured is True

    def test_is_configured_false_with_placeholder(self):
        client = _make_client(api_key="placeholder")
        assert client.is_configured is False

    def test_is_configured_false_with_empty(self):
        client = _make_client(api_key="")
        assert client.is_configured is False

    def test_build_headers(self):
        client = _make_client(api_key="sk-abc")
        headers = client._build_headers()
        assert headers["Authorization"] == "Bearer sk-abc"
        assert headers["Content-Type"] == "application/json"

    def test_build_payload_defaults(self):
        client = _make_client()
        messages = [ChatMessage(role="user", content="hello")]
        payload = client._build_payload(messages)
        assert payload["model"] == "deepseek-chat"
        assert payload["stream"] is False
        assert payload["temperature"] == 0.7
        assert payload["max_tokens"] == 2048
        assert len(payload["messages"]) == 1

    def test_build_payload_custom_params(self):
        client = _make_client()
        messages = [ChatMessage(role="user", content="hi")]
        payload = client._build_payload(
            messages, temperature=0.5, max_tokens=1024, stream=True,
        )
        assert payload["temperature"] == 0.5
        assert payload["max_tokens"] == 1024
        assert payload["stream"] is True

    def test_total_usage(self):
        client = _make_client()
        client._total_input_tokens = 100
        client._total_output_tokens = 50
        usage = client.total_usage
        assert usage.total_tokens == 150


# ---------------------------------------------------------------------------
# Chat Completion (Non-Streaming)
# ---------------------------------------------------------------------------


class TestChatCompletion:
    @pytest.mark.asyncio
    async def test_successful_completion(self):
        client = _make_client()
        resp = _mock_response(200, json_data=_success_json("Hello!"))

        # Pre-set client to avoid real HTTP call
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.is_closed = False
        client._client = mock_client

        result = await client.chat(
            messages=[ChatMessage(role="user", content="hi")],
        )
        assert isinstance(result, ChatCompletionResult)
        assert result.content == "Hello!"
        assert result.model == "deepseek-chat"
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 20
        assert result.finish_reason == "stop"
        assert client.total_usage.total_tokens == 30

    @pytest.mark.asyncio
    async def test_4xx_no_retry_raises_api_error(self):
        client = _make_client(max_retries=3, timeout=1)
        resp = _mock_response(400, text="Bad Request")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.is_closed = False
        client._client = mock_client

        with pytest.raises(DeepSeekAPIError) as exc_info:
            await client.chat(
                messages=[ChatMessage(role="user", content="hi")],
            )
        assert exc_info.value.status_code == 400
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_500_retries_then_raises(self):
        client = _make_client(max_retries=2, timeout=1)
        resp = _mock_response(500, text="Internal Server Error")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.is_closed = False
        client._client = mock_client

        with pytest.raises(DeepSeekAPIError):
            await client.chat(
                messages=[ChatMessage(role="user", content="hi")],
            )

        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_retries(self):
        import httpx

        client = _make_client(max_retries=2, timeout=1)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.TimeoutException("timeout"),
        )
        mock_client.is_closed = False
        client._client = mock_client

        with pytest.raises(DeepSeekTimeoutError):
            await client.chat(
                messages=[ChatMessage(role="user", content="hi")],
            )

        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_connection_error_retries(self):
        import httpx

        client = _make_client(max_retries=2, timeout=1)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused"),
        )
        mock_client.is_closed = False
        client._client = mock_client

        with pytest.raises(Exception):
            await client.chat(
                messages=[ChatMessage(role="user", content="hi")],
            )

        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        client = _make_client(max_retries=3, timeout=1)
        resp_500 = _mock_response(500, text="Server Error")
        resp_ok = _mock_response(200, json_data=_success_json("OK"))

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=[resp_500, resp_ok],
        )
        mock_client.is_closed = False
        client._client = mock_client

        result = await client.chat(
            messages=[ChatMessage(role="user", content="hi")],
        )
        assert result.content == "OK"
        assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


class TestStreaming:
    @pytest.mark.asyncio
    async def test_stream_success(self):
        client = _make_client()

        sse_lines = [
            'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":" world"},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # aiter_lines() returns an async generator (not callable)
        mock_resp.aiter_lines = lambda: _aiter_lines(sse_lines)
        mock_resp.aread = AsyncMock(return_value=b"error body")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.stream = MagicMock(return_value=mock_cm)
        client._client = mock_client

        chunks = []
        async for chunk in client.chat_stream(
            messages=[ChatMessage(role="user", content="hi")],
        ):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].content == "Hello"
        assert chunks[0].done is False
        assert chunks[1].content == " world"
        assert chunks[1].done is True
        assert chunks[1].usage is not None

    @pytest.mark.asyncio
    async def test_stream_error_raises(self):
        client = _make_client()

        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_resp.aread = AsyncMock(return_value=b"Bad Gateway")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.stream = MagicMock(return_value=mock_cm)
        client._client = mock_client

        with pytest.raises(DeepSeekAPIError):
            chunks = []
            async for chunk in client.chat_stream(
                messages=[ChatMessage(role="user", content="hi")],
            ):
                chunks.append(chunk)


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------


class TestClose:
    @pytest.mark.asyncio
    async def test_close(self):
        client = _make_client()
        mock_http_client = MagicMock()
        mock_http_client.is_closed = False
        mock_http_client.aclose = AsyncMock()
        client._client = mock_http_client
        await client.close()
        mock_http_client.aclose.assert_called_once()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_when_already_closed(self):
        client = _make_client()
        client._client = None
        await client.close()  # Should not raise


# ---------------------------------------------------------------------------
# TokenUsage
# ---------------------------------------------------------------------------


class TestTokenUsage:
    def test_total_tokens(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.total_tokens == 150

    def test_to_dict(self):
        usage = TokenUsage(input_tokens=10, output_tokens=20)
        d = usage.to_dict()
        assert d == {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


async def _aiter_lines(lines):
    for line in lines:
        yield line
