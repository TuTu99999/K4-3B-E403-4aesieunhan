"""Last source-of-truth check before notification creation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.tables import CandidateRecord, ChannelConfig, MessageHead, MessageSnapshot
from app.domain.candidate import CandidateMessage, message_from_snapshot
from app.domain.enums import FinalRecheckStatus, ResponsePolicy
from app.rules.duplicate_match import find_strict_duplicates
from app.rules.response_policy import find_valid_direct_response


@dataclass(frozen=True, slots=True)
class FinalRecheckResult:
    status: FinalRecheckStatus
    valid_response_key: str | None = None
    evidence_type: str | None = None


class FinalRechecker:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def check(self, candidate_id: str) -> FinalRecheckResult:
        with self._session_factory() as session:
            candidate = session.get(CandidateRecord, candidate_id)
            if candidate is None:
                raise LookupError(f"candidate {candidate_id} does not exist")
            original = session.get(MessageSnapshot, candidate.message_snapshot_id)
            if original is None:
                return FinalRecheckResult(FinalRecheckStatus.INACCESSIBLE)
            config = session.get(ChannelConfig, original.channel_config_id)
            if config is None or not config.enabled:
                return FinalRecheckResult(FinalRecheckStatus.INACCESSIBLE)
            head = session.get(MessageHead, candidate.message_key)
            if head is None:
                return FinalRecheckResult(FinalRecheckStatus.INACCESSIBLE)
            if head.is_deleted:
                return FinalRecheckResult(FinalRecheckStatus.DELETED)
            if head.current_content_version != candidate.content_version:
                return FinalRecheckResult(FinalRecheckStatus.CONTENT_VERSION_CHANGED)

            messages = self._load_current_messages(session, original.channel_config_id)
            by_reply_target = self._index_replies(messages)
            candidate_message = next(
                (item for item in messages if item.message_key == candidate.message_key),
                None,
            )
            if candidate_message is None:
                return FinalRecheckResult(FinalRecheckStatus.INACCESSIBLE)
            policy = ResponsePolicy(config.response_policy)
            response = find_valid_direct_response(
                candidate_message,
                by_reply_target.get(candidate.message_key, ()),
                policy,
            )
            if not response.responded:
                for duplicate in find_strict_duplicates(candidate_message, messages):
                    response = find_valid_direct_response(
                        duplicate,
                        by_reply_target.get(duplicate.message_key, ()),
                        policy,
                    )
                    if response.responded:
                        return FinalRecheckResult(
                            FinalRecheckStatus.RESPONDED,
                            response.response_key,
                            "DUPLICATE_DIRECT_REPLY",
                        )
            if response.responded:
                return FinalRecheckResult(
                    FinalRecheckStatus.RESPONDED,
                    response.response_key,
                    response.evidence_type,
                )
            return FinalRecheckResult(FinalRecheckStatus.STILL_OPEN)

    @staticmethod
    def _load_current_messages(
        session: Session, channel_config_id: int
    ) -> tuple[CandidateMessage, ...]:
        snapshots = session.scalars(
            select(MessageSnapshot)
            .join(MessageHead, MessageHead.current_snapshot_id == MessageSnapshot.id)
            .where(MessageSnapshot.channel_config_id == channel_config_id)
        ).all()
        return tuple(message_from_snapshot(snapshot) for snapshot in snapshots)

    @staticmethod
    def _index_replies(
        messages: tuple[CandidateMessage, ...]
    ) -> dict[str, tuple[CandidateMessage, ...]]:
        indexed: dict[str, list[CandidateMessage]] = {}
        for message in messages:
            if message.reply_to_key:
                indexed.setdefault(message.reply_to_key, []).append(message)
        return {key: tuple(value) for key, value in indexed.items()}
