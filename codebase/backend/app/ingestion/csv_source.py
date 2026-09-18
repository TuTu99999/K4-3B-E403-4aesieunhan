"""Offline message source backed by the canonical Discord CSV export."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.models import MessageRow
from app.ingestion.base import Page, SourceAttachment, SourceMessage
from app.ingestion.csv_loader import load_message_rows

try:
    _VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except ZoneInfoNotFoundError:
    # Modern Vietnamese timestamps are UTC+07 with no DST. The tzdata package is
    # declared for Windows, while this fallback keeps local validation bootstrappable.
    _VN_TZ = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")


def _to_source_message(row: MessageRow) -> SourceMessage:
    created_at_utc = row.created_at_vn.replace(tzinfo=_VN_TZ).astimezone(timezone.utc)
    return SourceMessage(
        source="csv",
        guild_id=row.guild,
        channel_id=row.channel,
        message_id=row.msg_id,
        author_id=row.author,
        is_bot=row.is_bot,
        message_type=row.msg_type.value,
        reply_to_message_id=row.reply_to,
        content=row.content,
        attachments=tuple(
            SourceAttachment(attachment_id=f"offline-{index + 1}")
            for index in range(row.n_attachments)
        ),
        created_at_utc=created_at_utc,
    )


def _message_sort_key(message: SourceMessage) -> tuple[str, str, str, str]:
    return (
        message.created_at_utc.isoformat(timespec="microseconds"),
        message.guild_id,
        message.channel_id,
        message.message_id,
    )


@dataclass(frozen=True, slots=True)
class _IndexedMessage:
    message: SourceMessage
    source_row: int

    @property
    def cursor_key(self) -> tuple[str, str, str, str, int]:
        return (*_message_sort_key(self.message), self.source_row)


def _encode_cursor(record: _IndexedMessage) -> str:
    payload = json.dumps(record.cursor_key, ensure_ascii=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str, str, str, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid offline message cursor") from exc
    if (
        not isinstance(value, list)
        or len(value) != 5
        or not all(isinstance(part, str) for part in value[:4])
        or not isinstance(value[4], int)
    ):
        raise ValueError("invalid offline message cursor")
    return tuple(value)  # type: ignore[return-value]


class CsvMessageSource:
    """In-memory indexed view of one validated CSV export."""

    source_kind = "csv"

    def __init__(self, path: str | Path) -> None:
        loaded = load_message_rows(path)
        indexed = tuple(
            sorted(
                (
                    _IndexedMessage(_to_source_message(row), source_row)
                    for source_row, row in enumerate(loaded.rows, start=2)
                ),
                key=lambda record: record.cursor_key,
            )
        )
        self._messages = tuple(record.message for record in indexed)
        self._by_key = {record.message.message_key: record.message for record in indexed}
        self._by_channel: dict[str, tuple[_IndexedMessage, ...]] = {}
        self._replies: dict[str, list[SourceMessage]] = {}

        channels: dict[str, list[_IndexedMessage]] = {}
        for record in indexed:
            message = record.message
            channel_ref = self.channel_ref(message.guild_id, message.channel_id)
            channels.setdefault(channel_ref, []).append(record)
            if message.reply_to_key:
                self._replies.setdefault(message.reply_to_key, []).append(message)
        self._by_channel = {key: tuple(value) for key, value in channels.items()}

    @staticmethod
    def channel_ref(guild_id: str, channel_id: str) -> str:
        return f"{guild_id}:{channel_id}"

    @property
    def channel_refs(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_channel))

    async def fetch_after(
        self, channel_ref: str, cursor: str | None, limit: int
    ) -> Page[SourceMessage]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        after = _decode_cursor(cursor) if cursor else None
        available = self._by_channel.get(channel_ref, ())
        remaining = [record for record in available if after is None or record.cursor_key > after]
        selected = tuple(remaining[:limit])
        next_cursor = _encode_cursor(selected[-1]) if selected else cursor
        return Page(
            records=tuple(record.message for record in selected),
            next_cursor=next_cursor,
            has_more=len(remaining) > len(selected),
        )

    async def fetch_message(self, message_key: str) -> SourceMessage | None:
        return self._by_key.get(message_key)

    async def fetch_direct_replies(self, message_key: str) -> list[SourceMessage]:
        return list(self._replies.get(message_key, ()))
