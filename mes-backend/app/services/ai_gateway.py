"""AI Inference Gateway with 3-level degradation.

Degradation chain:
  Level 1: DeepSeek API (full AI analysis)
  Level 2: Redis Cache (serve cached or station-latest response)
  Level 3: Rule Engine (keyword-based fixed responses)

Includes a circuit breaker to prevent cascading failures when
the DeepSeek API is consistently failing.

Usage:
    from app.services.ai_gateway import AIGateway
    gateway = AIGateway()
    # After Redis connects:
    from app.services.cache_store import RedisCacheStore
    gateway.set_cache_store(RedisCacheStore(redis_pool))

    result = await gateway.analyze(
        prompt="Analyze station efficiency",
        context={"station_id": "STA-01", "line_id": "L01"},
    )
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.services.cache_store import RedisCacheStore
from app.services.deepseek_client import (
    ChatCompletionResult,
    DeepSeekAPIError,
    DeepSeekClient,
    DeepSeekTimeoutError,
    ChatMessage,
)
from app.services.rule_engine import RuleEngine

logger = logging.getLogger("mes_backend.ai_gateway")

# Circuit breaker configuration
_ALLOWED_FAILS = 3
_FAILURE_WINDOW = 60.0
_CIRCUIT_COOLDOWN = 30.0

# Input validation (S-08)
_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
_MAX_PROMPT_LENGTH = 8000  # total prompt length limit (S-12)


class AIGateway:
    """Three-level degradation: DeepSeek API -> Redis Cache -> Rule Engine."""

    def __init__(
        self,
        api_key: str = "",
        api_url: str = "https://api.deepseek.com/v1/chat/completions",
        model: str = "deepseek-chat",
        timeout: int = 30,
        cache_client=None,
    ) -> None:
        # Support both no-arg and parametrized construction
        if api_key:
            self.deepseek = DeepSeekClient(
                api_key=api_key, api_url=api_url, model=model, timeout=timeout,
            )
        else:
            self.deepseek = DeepSeekClient(api_key="placeholder", timeout=timeout)

        self.cache: Optional[RedisCacheStore] = None
        self.rule_engine = RuleEngine()

        # If a cache_client was provided, use it directly
        if cache_client is not None:
            if isinstance(cache_client, RedisCacheStore):
                self.cache = cache_client
            else:
                self.cache = RedisCacheStore(redis_client=cache_client)

        # Circuit breaker state
        self._failures: list[float] = []
        self._circuit_open_until: float = 0.0

    def set_cache_store(self, cache_store: RedisCacheStore) -> None:
        """Inject a CacheStore instance after Redis connects."""
        self.cache = cache_store
        logger.info("AI Gateway: cache store injected")

    def _is_deepseek_healthy(self) -> bool:
        now = time.monotonic()
        if self._circuit_open_until > now:
            return False
        if self._circuit_open_until > 0 and now >= self._circuit_open_until:
            self._circuit_open_until = 0.0
            self._failures.clear()
            logger.info("Circuit breaker cooldown expired, allowing trial request")
        return True

    def _record_failure(self) -> None:
        now = time.monotonic()
        window_start = now - _FAILURE_WINDOW
        self._failures = [t for t in self._failures if t > window_start]
        self._failures.append(now)
        if len(self._failures) >= _ALLOWED_FAILS:
            self._circuit_open_until = now + _CIRCUIT_COOLDOWN
            logger.warning(
                "Circuit breaker OPEN: %d failures in %.0fs, cooldown %.0fs",
                len(self._failures), _FAILURE_WINDOW, _CIRCUIT_COOLDOWN,
            )

    def _record_success(self) -> None:
        if self._failures:
            self._failures.clear()
            self._circuit_open_until = 0.0

    @property
    def circuit_state(self) -> str:
        now = time.monotonic()
        if self._circuit_open_until > now:
            return "open"
        if self._circuit_open_until > 0:
            return "half_open"
        return "closed"

    @staticmethod
    def _validate_context_value(value: object) -> str:
        """Validate and sanitize a context value for prompt injection prevention (S-08)."""
        if value is None:
            return ""
        s = str(value)
        # Restrict to safe characters for ID fields
        if not _ID_PATTERN.match(s):
            logger.warning("Context value rejected (invalid format): %.50s...", s)
            return ""
        return s

    def _build_messages(
        self, prompt: str, context: Dict[str, object],
    ) -> List[ChatMessage]:
        # Use frontend-provided systemPrompt if available (from AiAnalysis.vue)
        if "systemPrompt" in context and isinstance(context["systemPrompt"], str):
            system_msg = context["systemPrompt"]
        else:
            system_msg = (
                "You are an AI manufacturing analysis assistant for an Edge MES "
                "system. Provide concise, data-driven analysis and actionable "
                "recommendations. Focus on manufacturing efficiency, work time "
                "optimization, line balance, therblig analysis, and quality "
                "improvement. 请用中文回答。"
            )
        enriched = prompt
        if context:
            ctx_parts = []
            for key in ("station_id", "line_id", "shift", "analysis_type"):
                val = self._validate_context_value(context.get(key))
                if val:
                    ctx_parts.append(f"{key}: {val}")
            # metrics: only allow if it's a dict (structured data)
            metrics = context.get("metrics")
            if isinstance(metrics, dict):
                safe_metrics = {
                    k: v for k, v in metrics.items()
                    if isinstance(k, str) and isinstance(v, (int, float, str, bool))
                }
                if safe_metrics:
                    ctx_parts.append(f"Current Metrics: {safe_metrics}")
            if ctx_parts:
                enriched = f"[Context: {'; '.join(ctx_parts)}]\n\n{prompt}"

        # Enforce prompt length limit (S-12)
        if len(enriched) > _MAX_PROMPT_LENGTH:
            logger.warning(
                "Prompt truncated from %d to %d chars",
                len(enriched), _MAX_PROMPT_LENGTH,
            )
            enriched = enriched[:_MAX_PROMPT_LENGTH] + "... [truncated]"

        return [
            ChatMessage(role="system", content=system_msg),
            ChatMessage(role="user", content=enriched),
        ]

    async def analyze(
        self,
        prompt: str = "",
        context: Optional[Dict[str, object]] = None,
        messages: Optional[List[ChatMessage]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Main AI analysis entry point with 3-level degradation.

        Args:
            prompt: The user's analysis query.
            context: Optional context dict (station_id, line_id, etc.).
            messages: Optional pre-built ChatMessage list (overrides prompt).
            stream: If True, returns streaming response dict.

        Returns:
            Dict with keys: content, level, model_source, streamed, generator.
        """
        ctx = context or {}

        # Build messages if not provided
        if messages is None:
            messages = self._build_messages(prompt, ctx)

        # Level 1: DeepSeek API
        if self._is_deepseek_healthy() and self.deepseek.is_configured:
            try:
                if stream:
                    return await self._try_deepseek_stream(prompt, messages, ctx)
                else:
                    return await self._try_deepseek_complete(prompt, messages, ctx)
            except (DeepSeekTimeoutError, DeepSeekAPIError, Exception) as e:
                self._record_failure()
                logger.warning("DeepSeek Level 1 failed: %s. Falling to cache.", e)
        elif not self.deepseek.is_configured:
            logger.debug("DeepSeek not configured, skipping to cache")

        # Level 2: Redis Cache
        if self.cache is not None:
            cached = await self._try_cache(prompt, ctx)
            if cached is not None:
                return cached

        # Level 3: Rule Engine (always succeeds)
        return self._try_rule_engine(prompt, ctx)

    async def _try_deepseek_complete(
        self,
        prompt: str,
        messages: List[ChatMessage],
        context: Dict[str, object],
    ) -> Dict[str, Any]:
        result: ChatCompletionResult = await self.deepseek.chat(messages=messages)
        self._record_success()
        await self._cache_response(prompt, context, result.content)
        return {
            "content": result.content,
            "level": "deepseek",
            "model_source": result.model,
            "streamed": False,
            "generator": None,
            "usage": result.usage.to_dict(),
        }

    async def _try_deepseek_stream(
        self,
        prompt: str,
        messages: List[ChatMessage],
        context: Dict[str, object],
    ) -> Dict[str, Any]:
        stream_gen = self.deepseek.chat_stream(messages=messages)

        async def _buffered_stream() -> AsyncGenerator[str, None]:
            full_response_parts: list[str] = []
            try:
                async for chunk in stream_gen:
                    full_response_parts.append(chunk.content)
                    yield chunk.content
            finally:
                full_response = "".join(full_response_parts)
                if full_response:
                    self._record_success()
                    await self._cache_response(prompt, context, full_response)

        return {
            "content": None,
            "level": "deepseek",
            "model_source": self.deepseek._model,
            "streamed": True,
            "generator": _buffered_stream(),
        }

    async def _cache_response(
        self, prompt: str, context: Dict[str, object], response: str,
    ) -> None:
        if self.cache is None:
            return
        try:
            key = RedisCacheStore.make_key(prompt, self.cache._namespace)
            await self.cache.set(key, response, ttl=1800)

            station_id = context.get("station_id")
            if station_id:
                await self.cache.set_station_latest(str(station_id), response)
        except Exception as e:
            logger.error("Failed to cache response: %s", e)

    async def _try_cache(
        self, prompt: str, context: Dict[str, object],
    ) -> Optional[Dict[str, Any]]:
        if self.cache is None:
            return None
        try:
            key = RedisCacheStore.make_key(prompt, self.cache._namespace)
            cached = await self.cache.get(key)
            if cached is not None:
                logger.info("Cache hit for prompt key: %s", key[:20])
                return {"content": cached, "level": "cache", "model_source": "cache", "streamed": False, "generator": None}

            station_id = context.get("station_id")
            if station_id:
                station_latest = await self.cache.get_station_latest(str(station_id))
                if station_latest is not None:
                    return {"content": station_latest, "level": "cache", "model_source": "cache", "streamed": False, "generator": None}
        except Exception as e:
            logger.warning("Cache lookup error: %s", e)
        return None

    def _try_rule_engine(
        self, prompt: str, context: Dict[str, object],
    ) -> Dict[str, Any]:
        response = self.rule_engine.generate_response(prompt, context)
        logger.info("Rule engine fallback for prompt: %.50s...", prompt)
        return {
            "content": response,
            "level": "rule_engine",
            "model_source": "rule_engine",
            "streamed": False,
            "generator": None,
        }

    async def analyze_stream(
        self,
        prompt: str,
        context: Optional[Dict[str, object]] = None,
        messages: Optional[List[ChatMessage]] = None,
    ) -> AsyncGenerator[str, None]:
        """Convenience method for streaming analysis."""
        result = await self.analyze(prompt, context, messages, stream=True)
        if result["streamed"] and result["generator"] is not None:
            async for chunk in result["generator"]:
                yield chunk
        elif result["content"]:
            yield result["content"]

    @property
    def is_healthy(self) -> bool:
        """Whether DeepSeek is reachable (circuit breaker closed)."""
        return self._is_deepseek_healthy() and self.deepseek.is_configured

    async def close(self) -> None:
        """Release resources held by the gateway (e.g. httpx client)."""
        if hasattr(self.deepseek, "close") and callable(self.deepseek.close):
            await self.deepseek.close()

    def get_status(self) -> Dict[str, Any]:
        """Get gateway status for monitoring/health endpoints."""
        return {
            "circuit_state": self.circuit_state,
            "failure_count": len(self._failures),
            "circuit_open_until": self._circuit_open_until,
            "deepseek_configured": self.deepseek.is_configured,
            "deepseek_usage": self.deepseek.total_usage.to_dict(),
            "cache_available": self.cache is not None,
        }

    async def analyze_therblig(
        self,
        station_id: str = "",
        therblig_stats: Optional[Dict[str, Any]] = None,
        mod_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Specialized therblig optimization analysis using ECRS framework.

        Args:
            station_id: Target workstation.
            therblig_stats: Dict mapping therblig names to stats dicts
                with keys: symbol, count, total_mod, is_waste.
            mod_data: Dict with MOD comparison data:
                actual_mod, target_mod, savings_mod, savings_pct.

        Returns:
            Analysis result dict with keys: content, level, model_source.
        """
        from app.services.prompt_templates import build_prompt

        data: Dict[str, object] = {"station_id": station_id}
        if therblig_stats:
            data["therblig_stats"] = therblig_stats
        if mod_data:
            data["mod_comparison"] = mod_data

        prompt = build_prompt("therblig_optimization", data)
        if prompt is None:
            return self._try_rule_engine(
                "Therblig optimization analysis",
                {"station_id": station_id},
            )

        return await self.analyze(
            prompt=prompt,
            context={"station_id": station_id, "analysis_type": "therblig_optimization"},
        )
