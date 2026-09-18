"""Read-only Discord REST message source with bounded retries."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

import httpx

from app.ingestion.base import (
    Page,
    SourceAttachment,
    SourceMessage,
    SourceNotAllowed,
    SourcePermissionDenied,
    SourceProtocolError,
    SourceTemporarilyUnavailable,
)

Sleep = Callable[[float], Awaitable[None]]


def _parse_timestamp(value: object, *, field: str, required: bool = False) -> datetime | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise SourceProtocolError(f"Discord response has invalid {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceProtocolError(f"Discord response has invalid {field}") from exc
    if parsed.tzinfo is None:
        raise SourceProtocolError(f"Discord response has timezone-free {field}")
    return parsed


def _required_id(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SourceProtocolError(f"Discord response is missing {key}")
    return value


class DiscordMessageSource:
    """Discord adapter restricted to an explicit channel allowlist."""

    source_kind = "discord"

    def __init__(
        self,
        token: str,
        allowed_channel_ids: frozenset[str] | set[str],
        *,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        base_backoff_seconds: float = 0.25,
        jitter_seconds: float = 0.1,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if not token.strip():
            raise ValueError("Discord token must not be blank")
        if not allowed_channel_ids:
            raise ValueError("Discord channel allowlist must not be empty")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self._allowed = frozenset(allowed_channel_ids)
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds
        self._jitter = jitter_seconds
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url="https://discord.com/api/v10",
            headers={"Authorization": f"Bot {token}"},
            timeout=httpx.Timeout(10.0),
        )

    async def __aenter__(self) -> DiscordMessageSource:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_after(
        self, channel_ref: str, cursor: str | None, limit: int
    ) -> Page[SourceMessage]:
        self._assert_allowed(channel_ref)
        page_limit = min(max(limit, 1), 100)
        params: dict[str, str | int] = {"limit": page_limit}
        if cursor:
            params["after"] = cursor
        response = await self._request("GET", f"/channels/{channel_ref}/messages", params=params)
        payload = self._json_list(response)
        messages = tuple(
            sorted(
                (self._convert(item, channel_ref) for item in payload),
                key=_snowflake,
            )
        )
        next_cursor = messages[-1].message_id if messages else cursor
        return Page(
            records=messages,
            next_cursor=next_cursor,
            has_more=len(messages) == page_limit,
        )

    async def fetch_message(self, message_key: str) -> SourceMessage | None:
        guild_id, channel_id, message_id = self._split_key(message_key)
        self._assert_allowed(channel_id)
        response = await self._request(
            "GET",
            f"/channels/{channel_id}/messages/{message_id}",
            allow_not_found=True,
        )
        if response.status_code == 404:
            return None
        message = self._convert(self._json_object(response), channel_id)
        if message.guild_id != guild_id:
            raise SourceProtocolError("Discord message guild does not match message key")
        return message

    async def fetch_direct_replies(self, message_key: str) -> list[SourceMessage]:
        _, channel_id, message_id = self._split_key(message_key)
        cursor: str | None = message_id
        replies: list[SourceMessage] = []
        # Discord has no direct-reply lookup endpoint. Bound the scan so reconciliation is safe.
        for _ in range(10):
            page = await self.fetch_after(channel_id, cursor, 100)
            replies.extend(item for item in page.records if item.reply_to_message_id == message_id)
            if not page.has_more or page.next_cursor == cursor:
                break
            cursor = page.next_cursor
        return replies

    def _assert_allowed(self, channel_id: str) -> None:
        if channel_id not in self._allowed:
            raise SourceNotAllowed("Discord channel is outside the configured allowlist")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        allow_not_found: bool = False,
    ) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.request(method, path, params=params)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= self._max_retries:
                    raise SourceTemporarilyUnavailable(
                        "Discord request failed after retries"
                    ) from exc
                await self._sleep(self._backoff(attempt))
                continue

            if response.status_code == 429:
                if attempt >= self._max_retries:
                    raise SourceTemporarilyUnavailable("Discord rate limit retry budget exhausted")
                await self._sleep(self._retry_after(response) + random.uniform(0, self._jitter))
                continue
            if response.status_code in {500, 502, 503, 504}:
                if attempt >= self._max_retries:
                    raise SourceTemporarilyUnavailable("Discord server retry budget exhausted")
                await self._sleep(self._backoff(attempt))
                continue
            if response.status_code in {401, 403}:
                raise SourcePermissionDenied("Discord rejected channel access")
            if allow_not_found and response.status_code == 404:
                return response
            if response.is_error:
                raise SourceProtocolError(f"Discord returned HTTP {response.status_code}")
            return response
        raise AssertionError("retry loop exited unexpectedly")

    def _backoff(self, attempt: int) -> float:
        return self._base_backoff * (2**attempt) + random.uniform(0, self._jitter)

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return max(float(header), 0.0)
            except ValueError:
                pass
        try:
            payload = response.json()
        except ValueError:
            return 1.0
        value = payload.get("retry_after") if isinstance(payload, dict) else None
        return max(float(value), 0.0) if isinstance(value, (int, float)) else 1.0

    @staticmethod
    def _json_list(response: httpx.Response) -> list[Mapping[str, Any]]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceProtocolError("Discord returned invalid JSON") from exc
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise SourceProtocolError("Discord message page is not a list of objects")
        return payload

    @staticmethod
    def _json_object(response: httpx.Response) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceProtocolError("Discord returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise SourceProtocolError("Discord message is not an object")
        return payload

    @staticmethod
    def _split_key(message_key: str) -> tuple[str, str, str]:
        parts = message_key.split(":", 2)
        if len(parts) != 3 or not all(parts):
            raise ValueError("message key must be guild:channel:message")
        return parts[0], parts[1], parts[2]

    @staticmethod
    def _convert(payload: Mapping[str, Any], channel_id: str) -> SourceMessage:
        author = payload.get("author")
        if not isinstance(author, dict):
            raise SourceProtocolError("Discord response is missing author")
        member = payload.get("member")
        role_values = member.get("roles", []) if isinstance(member, dict) else []
        roles = frozenset(str(role) for role in role_values if isinstance(role, str))
        reference = payload.get("message_reference")
        reply_to = reference.get("message_id") if isinstance(reference, dict) else None
        attachments_raw = payload.get("attachments", [])
        if not isinstance(attachments_raw, list):
            raise SourceProtocolError("Discord attachments must be a list")

        message_type = payload.get("type", 0)
        return SourceMessage(
            source="discord",
            guild_id=_required_id(payload, "guild_id"),
            channel_id=channel_id,
            thread_id=None,
            message_id=_required_id(payload, "id"),
            author_id=_required_id(author, "id"),
            author_roles=roles,
            is_bot=bool(author.get("bot", False)),
            is_webhook=bool(payload.get("webhook_id")),
            is_system=message_type not in {0, 19},
            message_type="reply" if reply_to else "message",
            reply_to_message_id=reply_to if isinstance(reply_to, str) else None,
            content=str(payload.get("content", "")),
            attachments=tuple(
                SourceAttachment(
                    attachment_id=str(item.get("id")) if item.get("id") else None,
                    filename=(
                        str(item.get("filename")) if item.get("filename") else None
                    ),
                    media_type=(
                        str(item.get("content_type"))
                        if item.get("content_type")
                        else None
                    ),
                    size_bytes=item.get("size") if isinstance(item.get("size"), int) else None,
                )
                for item in attachments_raw
                if isinstance(item, dict)
            ),
            created_at_utc=_parse_timestamp(
                payload.get("timestamp"), field="timestamp", required=True
            ),
            edited_at_utc=_parse_timestamp(
                payload.get("edited_timestamp"), field="edited_timestamp"
            ),
        )


def _snowflake(message: SourceMessage) -> int:
    try:
        return int(message.message_id)
    except ValueError as exc:
        raise SourceProtocolError("Discord message ID is not a snowflake") from exc
