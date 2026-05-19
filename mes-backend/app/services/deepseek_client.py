"""
DeepSeek API client with streaming support.

Encapsulates HTTP calls to DeepSeek API (OpenAI-compatible format).
Supports both synchronous and SSE streaming responses.
Tracks token usage for cost monitoring.

Reference: spec_phase4_celery_ai_onnx.md Section 3.1
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class DeepSeekError(Exception):
    """Base exception for DeepSeek API errors."""

    def __init__(self, message: str, status_code: int = 0):
        self.status_code = status_code
        super().__init__(message)


class DeepSeekTimeoutError(DeepSeekError):
    """Request exceeded timeout limit."""


class DeepSeekAPIError(DeepSeekError):
    """API returned a non-200 status code."""


@dataclass
class TokenUsage:
    """Token usage tracking for cost monitoring."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class ChatMessage:
    """A single chat message."""

    role: str
    content: str


@dataclass
class ChatCompletionResult:
    """Result from a non-streaming chat completion."""

    content: str
    model: str
    usage: TokenUsage
    finish_reason: str = "stop"


@dataclass
class StreamChunk:
    """A single chunk from a streaming response."""

    content: str
    done: bool = False
    usage: Optional[TokenUsage] = None


class DeepSeekClient:
    """HTTP client for DeepSeek API (OpenAI-compatible).

    Features:
    - Synchronous and streaming chat completions
    - Request timeout with configurable duration
    - Token usage tracking
    - Retry with exponential backoff for transient errors
    - Persistent httpx.AsyncClient with connection pooling
    """

    def __init__(
        self,
        api_key: str,
        api_url: str = "https://api.deepseek.com/v1/chat/completions",
        model: str = "deepseek-chat",
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self._api_key = api_key
        self._api_url = api_url
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create a persistent httpx.AsyncClient."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def close(self) -> None:
        """Close the persistent httpx client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_key != "placeholder")

    @property
    def total_usage(self) -> TokenUsage:
        return TokenUsage(
            input_tokens=self._total_input_tokens,
            output_tokens=self._total_output_tokens,
        )

    def _build_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    def _build_payload(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
        **extra: Any,
    ) -> dict:
        return {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            **extra,
        }

    async def chat(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> ChatCompletionResult:
        """Send a non-streaming chat completion request.

        Retries on transient errors (timeout, 5xx) up to max_retries.

        Raises:
            DeepSeekTimeoutError: If all retries exceed timeout.
            DeepSeekAPIError: If API returns non-200 status.
            DeepSeekError: For other failures.
        """
        payload = self._build_payload(messages, temperature, max_tokens, stream=False)

        last_exception: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                client = self._get_client()
                response = await client.post(
                    self._api_url,
                    json=payload,
                    headers=self._build_headers(),
                )

                if response.status_code == 200:
                    data = response.json()
                    content = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    usage_data = data.get("usage", {})
                    usage = TokenUsage(
                        input_tokens=usage_data.get("prompt_tokens", 0),
                        output_tokens=usage_data.get("completion_tokens", 0),
                    )
                    self._total_input_tokens += usage.input_tokens
                    self._total_output_tokens += usage.output_tokens

                    finish_reason = (
                        data.get("choices", [{}])[0].get("finish_reason", "stop")
                    )
                    logger.info(
                        "DeepSeek response: %d input, %d output tokens",
                        usage.input_tokens, usage.output_tokens,
                    )
                    return ChatCompletionResult(
                        content=content,
                        model=data.get("model", self._model),
                        usage=usage,
                        finish_reason=finish_reason,
                    )

                # Non-retryable client errors (4xx except 429)
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    raise DeepSeekAPIError(
                        f"DeepSeek API error: HTTP {response.status_code} - "
                        f"{response.text[:300]}",
                        status_code=response.status_code,
                    )

                # Retryable: 429 (rate limit) or 5xx
                last_exception = DeepSeekAPIError(
                    f"DeepSeek API error: HTTP {response.status_code}",
                    status_code=response.status_code,
                )
                logger.warning(
                    "DeepSeek API returned %d (attempt %d/%d)",
                    response.status_code, attempt, self._max_retries,
                )

            except httpx.TimeoutException:
                last_exception = DeepSeekTimeoutError(
                    f"DeepSeek API timed out ({self._timeout}s)"
                )
                logger.warning(
                    "DeepSeek API timeout (attempt %d/%d)",
                    attempt, self._max_retries,
                )
            except httpx.ConnectError as exc:
                last_exception = DeepSeekError(
                    f"DeepSeek API connection error: {exc}"
                )
                logger.warning(
                    "DeepSeek API connection error (attempt %d/%d): %s",
                    attempt, self._max_retries, exc,
                )

            # Exponential backoff with jitter: 1s, 2s, 4s (capped at 8s)
            if attempt < self._max_retries:
                backoff = min(2 ** (attempt - 1), 8)
                jitter = random.uniform(0, 0.5)
                await asyncio.sleep(backoff + jitter)

        # All retries exhausted
        raise last_exception or DeepSeekError("DeepSeek API request failed")

    async def chat_stream(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Send a streaming chat completion request.

        Yields StreamChunk objects as they arrive from the SSE stream.
        The final chunk will have done=True and may include usage stats.

        Retries on transient errors (timeout, 5xx) up to max_retries (P1 #43).
        """
        payload = self._build_payload(messages, temperature, max_tokens, stream=True)

        last_exception: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                client = self._get_client()
                async with client.stream(
                    "POST",
                    self._api_url,
                    json=payload,
                    headers=self._build_headers(),
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        exc = DeepSeekAPIError(
                            f"DeepSeek API stream error: HTTP {response.status_code} - "
                            f"{body[:300].decode(errors='replace')}",
                            status_code=response.status_code,
                        )
                        # Non-retryable client errors (4xx except 429)
                        if 400 <= response.status_code < 500 and response.status_code != 429:
                            raise exc
                        last_exception = exc
                        logger.warning(
                            "DeepSeek API stream returned %d (attempt %d/%d)",
                            response.status_code, attempt, self._max_retries,
                        )
                        if attempt < self._max_retries:
                            backoff = min(2 ** (attempt - 1), 8)
                            jitter = random.uniform(0, 0.5)
                            await asyncio.sleep(backoff + jitter)
                        continue

                    input_tokens = 0
                    output_tokens = 0

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue

                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break

                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = data.get("choices", [])
                        if not choices:
                            continue

                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        finish_reason = choices[0].get("finish_reason")

                        # Track token usage if provided in stream
                        usage_data = data.get("usage")
                        if usage_data:
                            input_tokens = usage_data.get("prompt_tokens", 0)
                            output_tokens = usage_data.get(
                                "completion_tokens", 0
                            )

                        yield StreamChunk(
                            content=content,
                            done=finish_reason == "stop",
                            usage=(
                                TokenUsage(
                                    input_tokens=input_tokens,
                                    output_tokens=output_tokens,
                                )
                                if finish_reason == "stop"
                                else None
                            ),
                        )

                    self._total_input_tokens += input_tokens
                    self._total_output_tokens += output_tokens
                    return  # Success, exit retry loop

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if isinstance(exc, httpx.TimeoutException):
                    last_exception = DeepSeekTimeoutError(
                        f"DeepSeek API stream timed out ({self._timeout}s)"
                    )
                else:
                    last_exception = DeepSeekError(
                        f"DeepSeek API stream connection error: {exc}"
                    )
                logger.warning(
                    "DeepSeek API stream error (attempt %d/%d): %s",
                    attempt, self._max_retries, exc,
                )
                if attempt < self._max_retries:
                    backoff = min(2 ** (attempt - 1), 8)
                    jitter = random.uniform(0, 0.5)
                    await asyncio.sleep(backoff + jitter)

        # All retries exhausted
        raise last_exception or DeepSeekError("DeepSeek API stream request failed")

    async def health_check(self) -> bool:
        """Check if DeepSeek API is reachable and properly configured.

        Returns True only if the API responds with a 2xx status.
        401 (auth error) means the API is reachable but credentials are wrong,
        so it should return False.
        """
        try:
            client = self._get_client()
            response = await client.get(
                "https://api.deepseek.com",
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            return response.status_code < 400
        except Exception:
            return False
