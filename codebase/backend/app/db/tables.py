"""Phase 1 durable ingestion tables."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ChannelConfig(Base):
    __tablename__ = "channel_configs"
    __table_args__ = (UniqueConstraint("guild_id", "channel_id", name="uq_channel_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    response_policy: Mapped[str] = mapped_column(
        String(32), nullable=False, default="any_other_human"
    )
    t_fast_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    t_normal_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    internal_destination_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class WorkerCursor(Base):
    __tablename__ = "worker_cursors"

    channel_config_id: Mapped[int] = mapped_column(
        ForeignKey("channel_configs.id", ondelete="CASCADE"), primary_key=True
    )
    last_message_id: Mapped[str | None] = mapped_column(Text)
    last_scanned_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    disabled_until: Mapped[datetime | None] = mapped_column(UTCDateTime())


class MessageSnapshot(Base):
    __tablename__ = "message_snapshots"
    __table_args__ = (
        UniqueConstraint("message_key", "content_version", name="uq_message_version"),
        Index("ix_snapshot_channel_message", "channel_id", "message_id"),
        Index("ix_snapshot_reply_to_key", "reply_to_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_config_id: Mapped[int] = mapped_column(
        ForeignKey("channel_configs.id", ondelete="CASCADE"), nullable=False
    )
    message_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    guild_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(128))
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    author_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    author_role_type: Mapped[str] = mapped_column(String(32), nullable=False)
    author_roles_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_webhook: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False)
    message_type: Mapped[str] = mapped_column(String(16), nullable=False)
    reply_to_key: Mapped[str | None] = mapped_column(String(512))
    content_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attachment_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at_utc: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    edited_at_utc: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deleted_at_utc: Mapped[datetime | None] = mapped_column(UTCDateTime())
    effective_at_utc: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ingested_at_utc: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now
    )


class MessageHead(Base):
    __tablename__ = "message_heads"

    message_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    current_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("message_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    current_content_version: Mapped[str] = mapped_column(String(64), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at_utc: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class CandidateRecord(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("message_key", "content_version", name="uq_candidate_version"),
        Index("ix_candidate_state_priority_eligible", "state", "priority", "eligible_at_utc"),
        Index("ix_candidate_message_key", "message_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    message_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("message_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    message_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str | None] = mapped_column(String(16))
    classification_intent: Mapped[str | None] = mapped_column(String(32))
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    effective_at_utc: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    eligible_at_utc: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    notified_at_utc: Mapped[datetime | None] = mapped_column(UTCDateTime())
    claimed_by: Mapped[str | None] = mapped_column(String(128))
    claim_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    snoozed_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    manual_reason_code: Mapped[str | None] = mapped_column(String(64))
    valid_response_key: Mapped[str | None] = mapped_column(String(512))
    response_evidence_type: Mapped[str | None] = mapped_column(String(32))
    superseded_by_version: Mapped[str | None] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False, default="rules-v1")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at_utc: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class RuleAudit(Base):
    __tablename__ = "rule_audits"
    __table_args__ = (
        UniqueConstraint("evaluation_key", name="uq_rule_audit_evaluation"),
        Index("ix_rule_audit_candidate_created", "candidate_id", "created_at_utc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
    message_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("message_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    evaluation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now
    )


class ClassificationRun(Base):
    __tablename__ = "classification_runs"
    __table_args__ = (
        Index("ix_classification_cache_status", "cache_key", "status"),
        Index("ix_classification_candidate_created", "candidate_id", "created_at_utc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    content_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    intent: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    token_usage_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at_utc: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now
    )
