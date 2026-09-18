from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.classifier.base import ClassifierProviderError, ClassifierSchemaError
from app.classifier.provider import OpenAICompatibleClassifierProvider
from app.classifier.schema import ClassificationRequest


def request() -> ClassificationRequest:
    return ClassificationRequest(
        message="Em không nộp được bài trước deadline",
        age_minutes=12,
        has_attachment=False,
        risk_hints=("DEADLINE", "SUBMISSION_BLOCKED"),
        prompt_version="classifier-v1",
    )


def response(content: str, *, status: int = 200, headers=None) -> httpx.Response:
    return httpx.Response(
        status,
        headers=headers,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"total_tokens": 42},
        },
    )


def make_provider(handler, *, retry_limit: int = 2, sleep=None):
    client = httpx.AsyncClient(
        base_url="https://router.test/v1",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICompatibleClassifierProvider(
        "private-key",
        "https://router.test/v1",
        "test-model",
        retry_limit=retry_limit,
        jitter_seconds=0,
        client=client,
        sleep=sleep or (lambda _: asyncio.sleep(0)),
    )
    return provider, client


def test_provider_parses_strict_json_and_usage() -> None:
    bodies: list[dict[str, object]] = []

    def handler(incoming: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(incoming.content))
        return response(
            json.dumps(
                {"intent": "SUPPORT_QUESTION", "priority": "URGENT", "confidence": 0.96}
            )
        )

    provider, client = make_provider(handler)
    try:
        result = asyncio.run(provider.classify(request()))
    finally:
        asyncio.run(client.aclose())

    assert result.response.priority.value == "URGENT"
    assert result.token_usage == {"total_tokens": 42}
    assert result.raw_response == (
        '{"intent": "SUPPORT_QUESTION", "priority": "URGENT", "confidence": 0.96}'
    )
    assert bodies[0]["response_format"]["type"] == "json_schema"
    assert "untrusted" in str(bodies[0]["messages"]).lower()


def test_provider_retries_rate_limit_then_succeeds() -> None:
    calls = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return response("{}", status=429, headers={"Retry-After": "0"})
        return response(
            '{"intent":"NON_ACTIONABLE","priority":null,"confidence":0.91}'
        )

    async def remember_delay(value: float) -> None:
        delays.append(value)

    provider, client = make_provider(handler, sleep=remember_delay)
    try:
        result = asyncio.run(provider.classify(request()))
    finally:
        asyncio.run(client.aclose())

    assert calls == result.provider_attempts == 2
    assert delays == [0.0]


def test_provider_reports_sanitized_auth_error() -> None:
    provider, client = make_provider(lambda _: response("secret body", status=401))
    try:
        with pytest.raises(ClassifierProviderError) as caught:
            asyncio.run(provider.classify(request()))
    finally:
        asyncio.run(client.aclose())

    assert caught.value.code == "PROVIDER_AUTH"
    assert "secret body" not in str(caught.value)
    assert "private-key" not in str(caught.value)


def test_provider_rejects_invalid_or_markdown_json() -> None:
    provider, client = make_provider(
        lambda _: response(
            '```json\n{"intent":"NON_ACTIONABLE","priority":null,"confidence":0.9}\n```'
        )
    )
    try:
        with pytest.raises(ClassifierSchemaError):
            asyncio.run(provider.classify(request()))
    finally:
        asyncio.run(client.aclose())
