"""Persistence operations used by the ingestion scanner."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tables import MessageHead, MessageSnapshot, WorkerCursor
from app.ingestion.normalizer import NormalizedMessage


class MessageStore:
    """Append-only snapshot persistence with one monotonic head per message."""

    def persist(
        self,
        session: Session,
        channel_config_id: int,
        message: NormalizedMessage,
    ) -> tuple[MessageSnapshot, bool]:
        snapshot = session.scalar(
            select(MessageSnapshot).where(
                MessageSnapshot.message_key == message.message_key,
                MessageSnapshot.content_version == message.content_version,
            )
        )
        created = snapshot is None
        if snapshot is None:
            snapshot = MessageSnapshot(
                channel_config_id=channel_config_id,
                message_key=message.message_key,
                content_version=message.content_version,
                source_type=message.source,
                guild_id=message.guild_id,
                channel_id=message.channel_id,
                thread_id=message.thread_id,
                message_id=message.message_id,
                author_id_hash=message.author_id_hash,
                author_role_type=message.author_role_type,
                author_roles_json=json.dumps(sorted(message.author_roles), separators=(",", ":")),
                is_bot=message.is_bot,
                is_webhook=message.is_webhook,
                is_system=message.is_system,
                message_type=message.message_type,
                reply_to_key=message.reply_to_key,
                content_redacted=message.content_redacted,
                content_hash=message.content_hash,
                attachment_metadata_json=json.dumps(
                    [item.model_dump(mode="json") for item in message.attachment_metadata],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                created_at_utc=message.created_at_utc,
                edited_at_utc=message.edited_at_utc,
                deleted_at_utc=message.deleted_at_utc,
                effective_at_utc=message.effective_at_utc,
                ingested_at_utc=datetime.now(timezone.utc),
            )
            session.add(snapshot)
            session.flush()

        head = session.get(MessageHead, message.message_key)
        should_advance = head is None or self._is_newer(message, head, session)
        if head is None:
            session.add(
                MessageHead(
                    message_key=message.message_key,
                    current_snapshot_id=snapshot.id,
                    current_content_version=message.content_version,
                    is_deleted=message.deleted_at_utc is not None,
                    updated_at_utc=message.effective_at_utc,
                )
            )
        elif should_advance:
            head.current_snapshot_id = snapshot.id
            head.current_content_version = message.content_version
            head.is_deleted = message.deleted_at_utc is not None
            head.updated_at_utc = message.effective_at_utc
        return snapshot, created

    @staticmethod
    def _is_newer(message: NormalizedMessage, head: MessageHead, session: Session) -> bool:
        if message.effective_at_utc > head.updated_at_utc:
            return True
        if message.effective_at_utc < head.updated_at_utc:
            return False
        current = session.get(MessageSnapshot, head.current_snapshot_id)
        if current is None:
            return True
        if message.deleted_at_utc is not None and current.deleted_at_utc is None:
            return True
        if message.deleted_at_utc is None and current.deleted_at_utc is not None:
            return False
        # A malformed offline export can repeat the same canonical key and timestamp.
        # A stable hash tie-breaker makes replay/out-of-order convergence deterministic.
        return message.content_version > head.current_content_version


def ensure_cursor(session: Session, channel_config_id: int) -> WorkerCursor:
    cursor = session.get(WorkerCursor, channel_config_id)
    if cursor is None:
        cursor = WorkerCursor(channel_config_id=channel_config_id, version=0)
        session.add(cursor)
        session.flush()
    return cursor
