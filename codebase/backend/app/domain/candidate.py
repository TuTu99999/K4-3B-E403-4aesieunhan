"""Persistence-independent facts and decisions for candidate rules."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from app.db.tables import MessageSnapshot
from app.domain.enums import CandidateState


@dataclass(frozen=True, slots=True)
class CandidateMessage:
    snapshot_id: int
    message_key: str
    content_version: str
    guild_id: str
    channel_id: str
    thread_id: str | None
    author_id_hash: str
    author_role_type: str
    is_bot: bool
    is_webhook: bool
    is_system: bool
    message_type: str
    reply_to_key: str | None
    content_redacted: str = field(repr=False)
    content_hash: str
    attachment_count: int
    created_at_utc: datetime
    edited_at_utc: datetime | None
    deleted_at_utc: datetime | None
    effective_at_utc: datetime

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at_utc is not None

    @property
    def is_attachment_only(self) -> bool:
        return not self.content_redacted.strip() and self.attachment_count > 0

    @property
    def conversation_scope(self) -> str:
        return self.thread_id or self.channel_id


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    eligible: bool
    checks: dict[str, bool]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResponseDecision:
    responded: bool
    reason_code: str
    response_key: str | None = None
    evidence_type: str | None = None


@dataclass(frozen=True, slots=True)
class PreclassificationDecision:
    target_state: CandidateState
    eligible_at_utc: datetime
    risk_hints: tuple[str, ...]
    effective_age_seconds: int
    reason_code: str


def message_from_snapshot(snapshot: MessageSnapshot) -> CandidateMessage:
    try:
        attachments = json.loads(snapshot.attachment_metadata_json)
    except json.JSONDecodeError:
        attachments = []
    if not isinstance(attachments, list):
        attachments = []
    return CandidateMessage(
        snapshot_id=snapshot.id,
        message_key=snapshot.message_key,
        content_version=snapshot.content_version,
        guild_id=snapshot.guild_id,
        channel_id=snapshot.channel_id,
        thread_id=snapshot.thread_id,
        author_id_hash=snapshot.author_id_hash,
        author_role_type=snapshot.author_role_type,
        is_bot=snapshot.is_bot,
        is_webhook=snapshot.is_webhook,
        is_system=snapshot.is_system,
        message_type=snapshot.message_type,
        reply_to_key=snapshot.reply_to_key,
        content_redacted=snapshot.content_redacted,
        content_hash=snapshot.content_hash,
        attachment_count=len(attachments),
        created_at_utc=snapshot.created_at_utc,
        edited_at_utc=snapshot.edited_at_utc,
        deleted_at_utc=snapshot.deleted_at_utc,
        effective_at_utc=snapshot.effective_at_utc,
    )
