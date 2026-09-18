"""Source-neutral ingestion contracts and error types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

SourceKind = Literal["csv", "discord"]


class SourceAttachment(BaseModel):
    """Attachment metadata only; file bytes never enter the ingestion pipeline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_id: str | None = None
    filename: str | None = None
    media_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class SourceMessage(BaseModel):
    """A message emitted by any configured source before normalization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: SourceKind
    guild_id: str = Field(min_length=1)
    channel_id: str = Field(min_length=1)
    thread_id: str | None = None
    message_id: str = Field(min_length=1)
    author_id: str = Field(min_length=1, repr=False, exclude=True)
    author_roles: frozenset[str] = frozenset()
    is_bot: bool = False
    is_webhook: bool = False
    is_system: bool = False
    message_type: Literal["message", "reply"]
    reply_to_message_id: str | None = None
    content: str = Field(repr=False, exclude=True)
    attachments: tuple[SourceAttachment, ...] = ()
    created_at_utc: datetime
    edited_at_utc: datetime | None = None
    deleted_at_utc: datetime | None = None

    @field_validator("created_at_utc", "edited_at_utc", "deleted_at_utc")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("source timestamps must be timezone-aware")
        return value

    @property
    def message_key(self) -> str:
        return f"{self.guild_id}:{self.channel_id}:{self.message_id}"

    @property
    def reply_to_key(self) -> str | None:
        if self.reply_to_message_id is None:
            return None
        return f"{self.guild_id}:{self.channel_id}:{self.reply_to_message_id}"


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    """One stable source page and the opaque cursor after that page."""

    records: tuple[T, ...]
    next_cursor: str | None
    has_more: bool


class MessageSource(Protocol):
    """Port implemented by offline fixtures and the live Discord API."""

    source_kind: SourceKind

    async def fetch_after(
        self, channel_ref: str, cursor: str | None, limit: int
    ) -> Page[SourceMessage]: ...

    async def fetch_message(self, message_key: str) -> SourceMessage | None: ...

    async def fetch_direct_replies(self, message_key: str) -> list[SourceMessage]: ...


class SourceError(RuntimeError):
    """Base class for source failures safe to expose in operational logs."""

    code = "SOURCE_ERROR"


class SourceRateLimited(SourceError):
    code = "RATE_LIMITED"

    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("message source rate limited the request")


class SourceTemporarilyUnavailable(SourceError):
    code = "TEMPORARILY_UNAVAILABLE"


class SourcePermissionDenied(SourceError):
    code = "PERMISSION_DENIED"


class SourceNotAllowed(SourcePermissionDenied):
    code = "CHANNEL_NOT_ALLOWED"


class SourceProtocolError(SourceError):
    code = "INVALID_SOURCE_RESPONSE"
