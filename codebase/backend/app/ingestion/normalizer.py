"""Privacy-preserving canonical message normalization."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from app.ingestion.base import SourceAttachment, SourceKind, SourceMessage

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PHONE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[ .-]?\d){9,10}(?!\d)")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^\s,'\"]{8,}"
)
_OPENAI_LIKE_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")


class AttachmentMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_id: str | None = None
    filename: str | None = None
    media_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class NormalizedMessage(BaseModel):
    """Canonical runtime message. Raw content must not be persisted or logged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_key: str
    source: SourceKind
    guild_id: str
    channel_id: str
    thread_id: str | None
    message_id: str
    author_id: str = Field(repr=False, exclude=True)
    author_id_hash: str
    author_roles: frozenset[str]
    author_role_type: str
    is_bot: bool
    is_webhook: bool
    is_system: bool
    message_type: str
    reply_to_key: str | None
    content_redacted: str = Field(repr=False)
    content_hash: str
    content_version: str
    attachment_metadata: tuple[AttachmentMetadata, ...]
    created_at_utc: datetime
    edited_at_utc: datetime | None
    deleted_at_utc: datetime | None
    effective_at_utc: datetime


def _canonical_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return normalized.strip()


def redact_content(content: str) -> str:
    """Redact common direct identifiers and credential-shaped values."""

    redacted = _EMAIL.sub("[REDACTED_EMAIL]", _canonical_text(content))
    redacted = _PHONE.sub("[REDACTED_PHONE]", redacted)
    redacted = _BEARER.sub("Bearer [REDACTED_TOKEN]", redacted)
    redacted = _OPENAI_LIKE_TOKEN.sub("[REDACTED_TOKEN]", redacted)
    return _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED_SECRET]", redacted)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _attachment_payload(attachments: tuple[SourceAttachment, ...]) -> list[dict[str, object]]:
    return [attachment.model_dump(mode="json") for attachment in attachments]


class MessageNormalizer:
    """Normalize source records and pseudonymize their author identifiers."""

    def __init__(
        self,
        identity_hash_salt: str,
        *,
        support_role_ids: frozenset[str] = frozenset(),
        approved_bot_ids: frozenset[str] = frozenset(),
    ) -> None:
        if len(identity_hash_salt.strip()) < 16:
            raise ValueError("identity hash salt must contain at least 16 characters")
        self._salt = identity_hash_salt.encode("utf-8")
        self._support_role_ids = support_role_ids
        self._approved_bot_ids = approved_bot_ids

    def normalize(self, source: SourceMessage) -> NormalizedMessage:
        canonical_content = _canonical_text(source.content)
        redacted = redact_content(canonical_content)
        content_hash = hmac.new(
            self._salt,
            canonical_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        author_hash = hmac.new(
            self._salt,
            f"{source.guild_id}:{source.author_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        attachments = _attachment_payload(source.attachments)
        version_payload = {
            "content_hash": content_hash,
            "edited_at": _iso(source.edited_at_utc),
            "deleted_at": _iso(source.deleted_at_utc),
            "attachments": attachments,
        }
        content_version = hashlib.sha256(
            json.dumps(
                version_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        effective_at = max(
            timestamp
            for timestamp in (
                source.created_at_utc,
                source.edited_at_utc,
                source.deleted_at_utc,
            )
            if timestamp is not None
        ).astimezone(timezone.utc)

        if source.is_bot and source.author_id in self._approved_bot_ids:
            role_type = "approved_bot"
        elif source.is_bot:
            role_type = "bot"
        elif source.author_roles & self._support_role_ids:
            role_type = "support"
        else:
            role_type = "student"

        return NormalizedMessage(
            message_key=source.message_key,
            source=source.source,
            guild_id=source.guild_id,
            channel_id=source.channel_id,
            thread_id=source.thread_id,
            message_id=source.message_id,
            author_id=source.author_id,
            author_id_hash=author_hash,
            author_roles=source.author_roles,
            author_role_type=role_type,
            is_bot=source.is_bot,
            is_webhook=source.is_webhook,
            is_system=source.is_system,
            message_type=source.message_type,
            reply_to_key=source.reply_to_key,
            content_redacted=redacted,
            content_hash=content_hash,
            content_version=content_version,
            attachment_metadata=tuple(
                AttachmentMetadata.model_validate(attachment) for attachment in attachments
            ),
            created_at_utc=source.created_at_utc.astimezone(timezone.utc),
            edited_at_utc=(
                source.edited_at_utc.astimezone(timezone.utc)
                if source.edited_at_utc is not None
                else None
            ),
            deleted_at_utc=(
                source.deleted_at_utc.astimezone(timezone.utc)
                if source.deleted_at_utc is not None
                else None
            ),
            effective_at_utc=effective_at,
        )
