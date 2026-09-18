"""OpenAI-compatible provider adapter for 9Router/OpenRouter-style endpoints."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import ValidationError

from app.classifier.base import (
    ClassifierProviderError,
    ClassifierSchemaError,
    ProviderResult,
)
from app.classifier.prompt import build_chat_messages
from app.classifier.schema import ClassificationRequest, ClassificationResponse

Sleep = Callable[[float], Awaitable[None]]


class OpenAICompatibleClassifierProvider:
    """Minimal chat-completions adapter with bounded transport retries."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        *,
        timeout_seconds: float = 30,
        retry_limit: int = 2,
        client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
        jitter_seconds: float = 0.1,
    ) -> None:
        if not api_key.strip():
            raise ValueError("classifier API key must not be blank")
        if retry_limit < 0:
            raise ValueError("retry_limit cannot be negative")
        self.model_name = model_name
        self._retry_limit = retry_limit
        self._sleep = sleep
        self._jitter = jitter_seconds
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def __aenter__(self) -> OpenAICompatibleClassifierProvider:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def classify(self, request: ClassificationRequest) -> ProviderResult:
        started = time.perf_counter()
        schema = ClassificationResponse.model_json_schema()
        payload = {
            "model": self.model_name,
            "messages": build_chat_messages(request),
            "temperature": 0,
            "max_tokens": 120,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "discord_support_classification",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        response: httpx.Response | None = None
        attempts = 0
        for attempt in range(self._retry_limit + 1):
            attempts = attempt + 1
            try:
                response = await self._client.post("/chat/completions", json=payload)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= self._retry_limit:
                    raise ClassifierProviderError(
                        "PROVIDER_TIMEOUT",
                        retryable=True,
                        latency_ms=self._elapsed_ms(started),
                        provider_attempts=attempts,
                    ) from exc
                await self._sleep(self._backoff(attempt))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self._retry_limit:
                    code = "PROVIDER_RATE_LIMIT" if response.status_code == 429 else "PROVIDER_5XX"
                    raise ClassifierProviderError(
                        code,
                        retryable=True,
                        latency_ms=self._elapsed_ms(started),
                        provider_attempts=attempts,
                    )
                await self._sleep(self._retry_delay(response, attempt))
                continue
            if response.status_code in {401, 403}:
                raise ClassifierProviderError(
                    "PROVIDER_AUTH",
                    retryable=False,
                    latency_ms=self._elapsed_ms(started),
                    provider_attempts=attempts,
                )
            if response.is_error:
                raise ClassifierProviderError(
                    "PROVIDER_REQUEST_REJECTED",
                    retryable=False,
                    latency_ms=self._elapsed_ms(started),
                    provider_attempts=attempts,
                )
            break

        if response is None:
            raise AssertionError("provider retry loop exited without a response")
        try:
            content, usage = self._extract_content(response)
        except ClassifierSchemaError as exc:
            raise ClassifierSchemaError(
                latency_ms=self._elapsed_ms(started),
                provider_attempts=attempts,
            ) from exc
        try:
            parsed = ClassificationResponse.model_validate_json(content)
        except (ValidationError, ValueError) as exc:
            raise ClassifierSchemaError(
                latency_ms=self._elapsed_ms(started),
                provider_attempts=attempts,
            ) from exc
        return ProviderResult(
            response=parsed,
            latency_ms=self._elapsed_ms(started),
            token_usage=usage,
            provider_attempts=attempts,
            raw_response=content,
        )

    def _backoff(self, attempt: int) -> float:
        return 0.25 * (2**attempt) + random.uniform(0, self._jitter)

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        value = response.headers.get("Retry-After")
        if value:
            try:
                return max(float(value), 0) + random.uniform(0, self._jitter)
            except ValueError:
                pass
        return self._backoff(attempt)

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(round((time.perf_counter() - started) * 1000), 0)

    @staticmethod
    def _extract_content(response: httpx.Response) -> tuple[str, dict[str, int]]:
        try:
            payload: Any = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ClassifierSchemaError() from exc
        if not isinstance(content, str):
            raise ClassifierSchemaError()
        usage_raw = payload.get("usage", {}) if isinstance(payload, dict) else {}
        usage = {
            key: value
            for key, value in usage_raw.items()
            if isinstance(key, str) and isinstance(value, int)
        } if isinstance(usage_raw, dict) else {}
        return content, usage
