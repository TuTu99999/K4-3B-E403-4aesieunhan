"""Candidate lifecycle transition validation."""

from __future__ import annotations

from enum import Enum

from app.domain.enums import CandidateState


class TransitionEvent(str, Enum):
    RULE_EVALUATION = "RULE_EVALUATION"
    RESPONSE_INVALIDATED = "RESPONSE_INVALIDATED"
    CONTENT_VERSION_CHANGED = "CONTENT_VERSION_CHANGED"


class InvalidStateTransition(ValueError):
    pass


_ALLOWED: dict[CandidateState, frozenset[CandidateState]] = {
    CandidateState.WAITING_THRESHOLD: frozenset(
        {
            CandidateState.CLASSIFYING,
            CandidateState.NEEDS_REVIEW,
            CandidateState.RESPONDED,
            CandidateState.DELETED,
            CandidateState.SUPERSEDED,
        }
    ),
    CandidateState.WAITING_NORMAL: frozenset(
        {
            CandidateState.OPEN_NORMAL,
            CandidateState.RESPONDED,
            CandidateState.DELETED,
            CandidateState.SUPERSEDED,
        }
    ),
    CandidateState.CLASSIFYING: frozenset(
        {
            CandidateState.CLASSIFICATION_PENDING,
            CandidateState.NON_ACTIONABLE,
            CandidateState.NEEDS_REVIEW,
            CandidateState.OPEN_NORMAL,
            CandidateState.OPEN_URGENT,
            CandidateState.WAITING_NORMAL,
            CandidateState.WAITING_THRESHOLD,
            CandidateState.RESPONDED,
            CandidateState.DELETED,
            CandidateState.SUPERSEDED,
        }
    ),
    CandidateState.CLASSIFICATION_PENDING: frozenset(
        {
            CandidateState.CLASSIFYING,
            CandidateState.NON_ACTIONABLE,
            CandidateState.NEEDS_REVIEW,
            CandidateState.WAITING_NORMAL,
            CandidateState.OPEN_NORMAL,
            CandidateState.OPEN_URGENT,
            CandidateState.RESPONDED,
            CandidateState.DELETED,
            CandidateState.SUPERSEDED,
        }
    ),
    CandidateState.OPEN_NORMAL: frozenset(
        {
            CandidateState.NOTIFIED,
            CandidateState.RESPONDED,
            CandidateState.DELETED,
            CandidateState.SUPERSEDED,
        }
    ),
    CandidateState.OPEN_URGENT: frozenset(
        {
            CandidateState.NOTIFIED,
            CandidateState.RESPONDED,
            CandidateState.DELETED,
            CandidateState.SUPERSEDED,
        }
    ),
    CandidateState.NEEDS_REVIEW: frozenset(
        {
            CandidateState.NOTIFIED,
            CandidateState.RESPONDED,
            CandidateState.DELETED,
            CandidateState.SUPERSEDED,
        }
    ),
    CandidateState.NOTIFIED: frozenset(
        {
            CandidateState.CLAIMED,
            CandidateState.SNOOZED,
            CandidateState.RESPONDED,
            CandidateState.DISMISSED,
            CandidateState.MANUAL_HANDLED,
            CandidateState.DELETED,
            CandidateState.SUPERSEDED,
        }
    ),
    CandidateState.CLAIMED: frozenset(
        {
            CandidateState.RESPONDED,
            CandidateState.SNOOZED,
            CandidateState.MANUAL_HANDLED,
            CandidateState.DISMISSED,
            CandidateState.DELETED,
            CandidateState.SUPERSEDED,
        }
    ),
    CandidateState.SNOOZED: frozenset(
        {
            CandidateState.NOTIFIED,
            CandidateState.RESPONDED,
            CandidateState.DELETED,
            CandidateState.SUPERSEDED,
        }
    ),
    CandidateState.REOPENED: frozenset(
        {
            CandidateState.CLASSIFYING,
            CandidateState.WAITING_THRESHOLD,
            CandidateState.NEEDS_REVIEW,
            CandidateState.OPEN_NORMAL,
            CandidateState.OPEN_URGENT,
            CandidateState.RESPONDED,
            CandidateState.DELETED,
        }
    ),
    CandidateState.NON_ACTIONABLE: frozenset(
        {CandidateState.DELETED, CandidateState.SUPERSEDED}
    ),
    CandidateState.DISMISSED: frozenset(
        {CandidateState.DELETED, CandidateState.SUPERSEDED}
    ),
    CandidateState.RESPONDED: frozenset(
        {
            CandidateState.OPEN_NORMAL,
            CandidateState.OPEN_URGENT,
            CandidateState.CLASSIFYING,
            CandidateState.WAITING_THRESHOLD,
            CandidateState.NEEDS_REVIEW,
            CandidateState.DELETED,
            CandidateState.SUPERSEDED,
        }
    ),
    CandidateState.MANUAL_HANDLED: frozenset(
        {CandidateState.DELETED, CandidateState.SUPERSEDED}
    ),
    CandidateState.DELETED: frozenset(),
    CandidateState.INACCESSIBLE: frozenset(
        {CandidateState.DELETED, CandidateState.SUPERSEDED}
    ),
    CandidateState.SUPERSEDED: frozenset(),
}


def ensure_transition(
    current: CandidateState,
    target: CandidateState,
    *,
    event: TransitionEvent = TransitionEvent.RULE_EVALUATION,
) -> bool:
    """Validate a transition and return False for an idempotent no-op."""

    if current == target:
        return False
    if target is CandidateState.SUPERSEDED and event is not TransitionEvent.CONTENT_VERSION_CHANGED:
        raise InvalidStateTransition("SUPERSEDED requires a content-version change")
    if current is CandidateState.RESPONDED and target in {
        CandidateState.CLASSIFYING,
        CandidateState.WAITING_THRESHOLD,
        CandidateState.OPEN_NORMAL,
        CandidateState.OPEN_URGENT,
        CandidateState.NEEDS_REVIEW,
    } and event is not TransitionEvent.RESPONSE_INVALIDATED:
        raise InvalidStateTransition("RESPONDED can reopen only after response invalidation")
    if target not in _ALLOWED.get(current, frozenset()):
        raise InvalidStateTransition(f"transition {current.value} -> {target.value} is not allowed")
    return True
