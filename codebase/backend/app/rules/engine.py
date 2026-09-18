"""Database-backed deterministic candidate generation and reconciliation."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.tables import (
    CandidateRecord,
    ChannelConfig,
    MessageHead,
    MessageSnapshot,
    RuleAudit,
)
from app.domain.candidate import CandidateMessage, ResponseDecision, message_from_snapshot
from app.domain.enums import CandidateState, ResponsePolicy
from app.domain.state_machine import TransitionEvent, ensure_transition
from app.rules.duplicate_match import find_strict_duplicates
from app.rules.eligibility import RULE_VERSION, evaluate_eligibility
from app.rules.preclassification import decide_preclassification_state
from app.rules.response_policy import find_valid_direct_response

_UNCHANGED_TERMINAL = frozenset(
    {
        CandidateState.NON_ACTIONABLE,
        CandidateState.DISMISSED,
        CandidateState.MANUAL_HANDLED,
        CandidateState.DELETED,
        CandidateState.SUPERSEDED,
    }
)


@dataclass(frozen=True, slots=True)
class RuleRunSummary:
    channel_config_id: int
    messages_evaluated: int
    candidates_created: int
    candidates_excluded: int
    state_changes: int
    audits_created: int
    state_counts: dict[str, int]


class CandidateRuleEngine:
    """Evaluate current message heads without invoking an LLM or notifier."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        duplicate_window: timedelta = timedelta(minutes=10),
        rule_version: str = RULE_VERSION,
    ) -> None:
        self._session_factory = session_factory
        self._duplicate_window = duplicate_window
        self._rule_version = rule_version

    def evaluate_channel(
        self,
        channel_config_id: int,
        *,
        now: datetime | None = None,
    ) -> RuleRunSummary:
        evaluation_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._session_factory.begin() as session:
            config = session.get(ChannelConfig, channel_config_id)
            if config is None:
                raise LookupError(f"channel config {channel_config_id} does not exist")
            try:
                policy = ResponsePolicy(config.response_policy)
            except ValueError as exc:
                raise ValueError(f"unsupported response policy: {config.response_policy}") from exc

            messages = self._load_current_messages(session, channel_config_id)
            by_reply_target = self._index_replies(messages)
            created = excluded = state_changes = audits_created = 0

            for message in messages:
                if message.is_deleted:
                    state_changes += self._close_deleted_message(
                        session, message, evaluation_time
                    )
                    audits_created += self._audit(
                        session,
                        message,
                        candidate=None,
                        decision="EXCLUDED_DELETED",
                        material={"deleted": True},
                    )
                    excluded += 1
                    continue

                state_changes += self._close_previous_versions(
                    session, message, evaluation_time
                )

                eligibility = evaluate_eligibility(
                    message,
                    channel_enabled=config.enabled,
                )
                if not eligibility.eligible:
                    audits_created += self._audit(
                        session,
                        message,
                        candidate=None,
                        decision="EXCLUDED_INELIGIBLE",
                        material={
                            "eligibility_checks": eligibility.checks,
                            "reason_codes": eligibility.reason_codes,
                        },
                    )
                    excluded += 1
                    continue

                candidate, was_created = self._get_or_create_candidate(
                    session, message, config.t_normal_minutes, evaluation_time
                )
                created += int(was_created)
                response = find_valid_direct_response(
                    message,
                    by_reply_target.get(message.message_key, ()),
                    policy,
                )
                if not response.responded:
                    response = self._find_duplicate_response(
                        message,
                        messages,
                        by_reply_target,
                        policy,
                    )

                preclassification = decide_preclassification_state(
                    message,
                    now=evaluation_time,
                    t_fast_minutes=config.t_fast_minutes,
                    t_normal_minutes=config.t_normal_minutes,
                )
                target = (
                    CandidateState.RESPONDED
                    if response.responded
                    else self._target_without_response(
                        candidate,
                        preclassification.target_state,
                        now=evaluation_time,
                    )
                )
                state_changes += self._apply_rule_state(
                    candidate,
                    target,
                    response,
                    eligible_at=preclassification.eligible_at_utc,
                    now=evaluation_time,
                )
                audits_created += self._audit(
                    session,
                    message,
                    candidate=candidate,
                    decision=target.value,
                    material={
                        "eligibility_checks": eligibility.checks,
                        "response_policy": policy.value,
                        "valid_response_key": response.response_key,
                        "response_evidence_type": response.evidence_type,
                        "risk_hints": preclassification.risk_hints,
                        "effective_age_seconds": preclassification.effective_age_seconds,
                        "reason_code": (
                            response.reason_code
                            if response.responded
                            else preclassification.reason_code
                        ),
                    },
                )

            state_counts = self._state_counts(session, channel_config_id)
            return RuleRunSummary(
                channel_config_id=channel_config_id,
                messages_evaluated=len(messages),
                candidates_created=created,
                candidates_excluded=excluded,
                state_changes=state_changes,
                audits_created=audits_created,
                state_counts=state_counts,
            )

    @staticmethod
    def _load_current_messages(
        session: Session, channel_config_id: int
    ) -> tuple[CandidateMessage, ...]:
        snapshots = session.scalars(
            select(MessageSnapshot)
            .join(MessageHead, MessageHead.current_snapshot_id == MessageSnapshot.id)
            .where(MessageSnapshot.channel_config_id == channel_config_id)
            .order_by(
                MessageSnapshot.effective_at_utc,
                MessageSnapshot.message_key,
            )
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

    def _find_duplicate_response(
        self,
        message: CandidateMessage,
        messages: tuple[CandidateMessage, ...],
        replies: dict[str, tuple[CandidateMessage, ...]],
        policy: ResponsePolicy,
    ) -> ResponseDecision:
        duplicates = find_strict_duplicates(
            message,
            messages,
            window=self._duplicate_window,
        )
        for duplicate in duplicates:
            decision = find_valid_direct_response(
                duplicate,
                replies.get(duplicate.message_key, ()),
                policy,
            )
            if decision.responded:
                return ResponseDecision(
                    True,
                    "STRICT_DUPLICATE_RESPONDED",
                    response_key=decision.response_key,
                    evidence_type="DUPLICATE_DIRECT_REPLY",
                )
        return ResponseDecision(False, "NO_VALID_RESPONSE")

    def _get_or_create_candidate(
        self,
        session: Session,
        message: CandidateMessage,
        t_normal_minutes: int,
        now: datetime,
    ) -> tuple[CandidateRecord, bool]:
        candidate = session.scalar(
            select(CandidateRecord).where(
                CandidateRecord.message_key == message.message_key,
                CandidateRecord.content_version == message.content_version,
            )
        )
        if candidate is not None:
            return candidate, False
        candidate = CandidateRecord(
            id=str(uuid.uuid4()),
            message_snapshot_id=message.snapshot_id,
            message_key=message.message_key,
            content_version=message.content_version,
            state=CandidateState.WAITING_THRESHOLD.value,
            effective_at_utc=message.effective_at_utc,
            eligible_at_utc=message.effective_at_utc
            + timedelta(minutes=t_normal_minutes),
            rule_version=self._rule_version,
            version=1,
            created_at_utc=now,
            updated_at_utc=now,
        )
        session.add(candidate)
        session.flush()
        return candidate, True

    @staticmethod
    def _target_without_response(
        candidate: CandidateRecord,
        preclassification_target: CandidateState,
        *,
        now: datetime,
    ) -> CandidateState:
        current = CandidateState(candidate.state)
        stable_states = {
            CandidateState.CLASSIFICATION_PENDING,
            CandidateState.NEEDS_REVIEW,
            CandidateState.OPEN_NORMAL,
            CandidateState.OPEN_URGENT,
            CandidateState.NOTIFIED,
            CandidateState.CLAIMED,
            CandidateState.SNOOZED,
        }
        if current in stable_states:
            return current
        if current is CandidateState.WAITING_NORMAL:
            return (
                CandidateState.OPEN_NORMAL
                if now >= candidate.eligible_at_utc
                else CandidateState.WAITING_NORMAL
            )
        return preclassification_target

    def _close_previous_versions(
        self,
        session: Session,
        message: CandidateMessage,
        now: datetime,
    ) -> int:
        previous = session.scalars(
            select(CandidateRecord).where(
                CandidateRecord.message_key == message.message_key,
                CandidateRecord.content_version != message.content_version,
                CandidateRecord.state.notin_(
                    [CandidateState.DELETED.value, CandidateState.SUPERSEDED.value]
                ),
            )
        ).all()
        changed = 0
        for candidate in previous:
            current = CandidateState(candidate.state)
            if ensure_transition(
                current,
                CandidateState.SUPERSEDED,
                event=TransitionEvent.CONTENT_VERSION_CHANGED,
            ):
                candidate.state = CandidateState.SUPERSEDED.value
                candidate.superseded_by_version = message.content_version
                candidate.version += 1
                candidate.updated_at_utc = now
                changed += 1
        return changed

    @staticmethod
    def _close_deleted_message(
        session: Session,
        message: CandidateMessage,
        now: datetime,
    ) -> int:
        candidates = session.scalars(
            select(CandidateRecord).where(
                CandidateRecord.message_key == message.message_key,
                CandidateRecord.state.notin_(
                    [CandidateState.DELETED.value, CandidateState.SUPERSEDED.value]
                ),
            )
        ).all()
        changed = 0
        for candidate in candidates:
            current = CandidateState(candidate.state)
            if ensure_transition(current, CandidateState.DELETED):
                candidate.state = CandidateState.DELETED.value
                candidate.version += 1
                candidate.updated_at_utc = now
                changed += 1
        return changed

    @staticmethod
    def _apply_rule_state(
        candidate: CandidateRecord,
        target: CandidateState,
        response: ResponseDecision,
        *,
        eligible_at: datetime,
        now: datetime,
    ) -> int:
        current = CandidateState(candidate.state)
        if current in _UNCHANGED_TERMINAL:
            return 0
        event = (
            TransitionEvent.RESPONSE_INVALIDATED
            if current is CandidateState.RESPONDED and target is not CandidateState.RESPONDED
            else TransitionEvent.RULE_EVALUATION
        )
        state_changed = ensure_transition(current, target, event=event)
        fields_changed = candidate.eligible_at_utc != eligible_at
        response_key = response.response_key if response.responded else None
        evidence_type = response.evidence_type if response.responded else None
        fields_changed = fields_changed or candidate.valid_response_key != response_key
        fields_changed = fields_changed or candidate.response_evidence_type != evidence_type
        if not state_changed and not fields_changed:
            return 0
        candidate.state = target.value
        candidate.eligible_at_utc = eligible_at
        candidate.valid_response_key = response_key
        candidate.response_evidence_type = evidence_type
        candidate.version += 1
        candidate.updated_at_utc = now
        return 1

    def _audit(
        self,
        session: Session,
        message: CandidateMessage,
        *,
        candidate: CandidateRecord | None,
        decision: str,
        material: dict[str, object],
    ) -> int:
        payload = {
            "rule_version": self._rule_version,
            **material,
        }
        fingerprint_payload = {
            "rule_version": self._rule_version,
            "message_key": message.message_key,
            "content_version": message.content_version,
            "decision": decision,
            "eligibility_checks": material.get("eligibility_checks"),
            "response_policy": material.get("response_policy"),
            "valid_response_key": material.get("valid_response_key"),
            "response_evidence_type": material.get("response_evidence_type"),
            "risk_hints": material.get("risk_hints"),
            "reason_code": material.get("reason_code"),
        }
        evaluation_key = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        exists = session.scalar(
            select(RuleAudit.id).where(RuleAudit.evaluation_key == evaluation_key)
        )
        if exists is not None:
            return 0
        session.add(
            RuleAudit(
                candidate_id=candidate.id if candidate else None,
                message_snapshot_id=message.snapshot_id,
                rule_version=self._rule_version,
                decision=decision,
                payload_json=json.dumps(
                    payload,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                evaluation_key=evaluation_key,
            )
        )
        return 1

    @staticmethod
    def _state_counts(session: Session, channel_config_id: int) -> dict[str, int]:
        records = session.scalars(
            select(CandidateRecord)
            .join(
                MessageSnapshot,
                MessageSnapshot.id == CandidateRecord.message_snapshot_id,
            )
            .where(MessageSnapshot.channel_config_id == channel_config_id)
        ).all()
        counts: dict[str, int] = {}
        for record in records:
            counts[record.state] = counts.get(record.state, 0) + 1
        return dict(sorted(counts.items()))
