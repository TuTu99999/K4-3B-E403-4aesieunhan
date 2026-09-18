"""Build minimal redacted context for one candidate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classifier.prompt import PROMPT_VERSION
from app.classifier.schema import ClassificationRequest
from app.db.tables import CandidateRecord, ChannelConfig, MessageHead, MessageSnapshot
from app.domain.candidate import CandidateMessage, message_from_snapshot
from app.rules.risk_hints import detect_risk_hints


@dataclass(frozen=True, slots=True)
class ClassificationEnvelope:
    candidate_id: str
    content_version: str
    request: ClassificationRequest
    request_hash: str
    context_hash: str
    cache_key: str
    t_normal_minutes: int


class ClassificationContextBuilder:
    def __init__(
        self,
        *,
        context_limit: int = 3,
        context_window_minutes: int = 30,
        payload_max_chars: int = 6000,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        if not 0 <= context_limit <= 3:
            raise ValueError("context_limit must be between 0 and 3")
        if payload_max_chars < 500:
            raise ValueError("payload_max_chars must be at least 500")
        self._limit = context_limit
        self._window = timedelta(minutes=context_window_minutes)
        self._max_chars = payload_max_chars
        self.prompt_version = prompt_version

    def build(
        self,
        session: Session,
        candidate: CandidateRecord,
        *,
        model_name: str,
        now: datetime,
    ) -> ClassificationEnvelope:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        current_snapshot = session.get(MessageSnapshot, candidate.message_snapshot_id)
        if current_snapshot is None:
            raise LookupError("candidate source snapshot does not exist")
        config = session.get(ChannelConfig, current_snapshot.channel_config_id)
        if config is None:
            raise LookupError("candidate channel config does not exist")
        current = message_from_snapshot(current_snapshot)
        messages = self._load_scope_messages(session, current_snapshot.channel_config_id, current)
        before_candidates = [
            item for item in messages if item.effective_at_utc < current.effective_at_utc
        ]
        after_candidates = [
            item for item in messages if item.effective_at_utc > current.effective_at_utc
        ]
        before = self._select_context(before_candidates[-self._limit :])
        after = self._select_context(after_candidates[: self._limit])

        message_text = self._truncate(current.content_redacted, min(self._max_chars // 2, 3000))
        remaining = max(self._max_chars - len(message_text), 0)
        before, remaining = self._fit_budget(before, remaining)
        after, _ = self._fit_budget(after, remaining)
        age_minutes = max(
            int((now.astimezone(timezone.utc) - current.effective_at_utc).total_seconds() // 60),
            0,
        )
        request = ClassificationRequest(
            message=message_text,
            context_before=before,
            context_after=after,
            age_minutes=age_minutes,
            has_attachment=current.attachment_count > 0,
            risk_hints=detect_risk_hints(current.content_redacted),
            prompt_version=self.prompt_version,
        )
        context_payload = json.dumps(
            {
                "before": before,
                "after": after,
                "age_bucket": (
                    "NORMAL_DUE"
                    if age_minutes >= config.t_normal_minutes
                    else "BEFORE_NORMAL"
                ),
                "has_attachment": request.has_attachment,
                "risk_hints": request.risk_hints,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        context_hash = hashlib.sha256(context_payload.encode("utf-8")).hexdigest()
        cache_material = ":".join(
            (candidate.content_version, self.prompt_version, model_name, context_hash)
        )
        cache_key = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()
        return ClassificationEnvelope(
            candidate_id=candidate.id,
            content_version=candidate.content_version,
            request=request,
            request_hash=request.canonical_hash(),
            context_hash=context_hash,
            cache_key=cache_key,
            t_normal_minutes=config.t_normal_minutes,
        )

    def _load_scope_messages(
        self,
        session: Session,
        channel_config_id: int,
        current: CandidateMessage,
    ) -> list[CandidateMessage]:
        lower = current.effective_at_utc - self._window
        upper = current.effective_at_utc + self._window
        snapshots = session.scalars(
            select(MessageSnapshot)
            .join(MessageHead, MessageHead.current_snapshot_id == MessageSnapshot.id)
            .where(
                MessageSnapshot.channel_config_id == channel_config_id,
                MessageSnapshot.effective_at_utc >= lower,
                MessageSnapshot.effective_at_utc <= upper,
                MessageSnapshot.id != current.snapshot_id,
            )
            .order_by(MessageSnapshot.effective_at_utc, MessageSnapshot.message_key)
        ).all()
        messages = [message_from_snapshot(snapshot) for snapshot in snapshots]
        return [
            message
            for message in messages
            if message.conversation_scope == current.conversation_scope
            and not message.is_deleted
        ]

    @staticmethod
    def _select_context(messages: list[CandidateMessage]) -> tuple[str, ...]:
        selected: list[str] = []
        for message in messages:
            text = message.content_redacted.strip()
            if not text:
                continue
            if message.is_bot and len(text) > 500:
                continue
            selected.append(text)
        return tuple(selected)

    def _fit_budget(
        self, items: tuple[str, ...], remaining: int
    ) -> tuple[tuple[str, ...], int]:
        fitted: list[str] = []
        for item in items:
            if remaining <= 0:
                break
            value = self._truncate(item, min(800, remaining))
            if value:
                fitted.append(value)
                remaining -= len(value)
        return tuple(fitted), remaining

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        if limit <= 1:
            return value[:limit]
        return value[: limit - 1] + "…"
