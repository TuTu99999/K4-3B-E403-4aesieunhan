from __future__ import annotations

import asyncio

import httpx
import pytest

from app.ingestion.base import SourceNotAllowed, SourcePermissionDenied
from app.ingestion.discord_source import DiscordMessageSource


def discord_payload(message_id: str = "100", *, reply_to: str | None = None) -> dict:
    payload = {
        "id": message_id,
        "guild_id": "10",
        "channel_id": "20",
        "author": {"id": "30", "bot": False},
        "member": {"roles": ["40"]},
        "content": "Em cần hỗ trợ",
        "timestamp": "2026-09-18T02:00:00+00:00",
        "edited_timestamp": None,
        "attachments": [],
        "type": 19 if reply_to else 0,
    }
    if reply_to:
        payload["message_reference"] = {"message_id": reply_to}
    return payload


def test_discord_source_retries_429_and_preserves_retry_after() -> None:
    calls = 0
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"retry_after": 0.75}, request=request)
        return httpx.Response(200, json=[discord_payload()], request=request)

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://discord.test"
    )
    source = DiscordMessageSource(
        "test-token",
        {"20"},
        client=client,
        jitter_seconds=0,
        sleep=fake_sleep,
    )

    page = asyncio.run(source.fetch_after("20", None, 100))
    asyncio.run(client.aclose())

    assert calls == 2
    assert waits == [0.75]
    assert page.records[0].message_key == "10:20:100"


def test_discord_source_retries_5xx_with_exponential_backoff() -> None:
    calls = 0
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        status = 503 if calls < 3 else 200
        return httpx.Response(status, json=[] if status == 200 else {}, request=request)

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://discord.test"
    )
    source = DiscordMessageSource(
        "test-token",
        {"20"},
        client=client,
        base_backoff_seconds=0.5,
        jitter_seconds=0,
        sleep=fake_sleep,
    )

    asyncio.run(source.fetch_after("20", None, 100))
    asyncio.run(client.aclose())

    assert waits == [0.5, 1.0]


def test_discord_source_rejects_403_without_leaking_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="sensitive upstream body", request=request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://discord.test"
    )
    source = DiscordMessageSource("test-token", {"20"}, client=client)

    with pytest.raises(SourcePermissionDenied, match="rejected channel access") as error:
        asyncio.run(source.fetch_after("20", None, 10))
    asyncio.run(client.aclose())

    assert "sensitive" not in str(error.value)


def test_discord_source_enforces_allowlist_before_http() -> None:
    source = DiscordMessageSource("test-token", {"20"})

    with pytest.raises(SourceNotAllowed):
        asyncio.run(source.fetch_after("99", None, 10))
    asyncio.run(source.aclose())


def test_discord_source_retries_timeout() -> None:
    calls = 0
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("fixture timeout", request=request)
        return httpx.Response(200, json=[], request=request)

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://discord.test"
    )
    source = DiscordMessageSource(
        "test-token",
        {"20"},
        client=client,
        base_backoff_seconds=0.25,
        jitter_seconds=0,
        sleep=fake_sleep,
    )

    asyncio.run(source.fetch_after("20", None, 10))
    asyncio.run(client.aclose())

    assert calls == 2
    assert waits == [0.25]


def test_discord_missing_message_returns_none_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, request=request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://discord.test"
    )
    source = DiscordMessageSource("test-token", {"20"}, client=client)

    result = asyncio.run(source.fetch_message("10:20:100"))
    asyncio.run(client.aclose())

    assert result is None
    assert calls == 1
