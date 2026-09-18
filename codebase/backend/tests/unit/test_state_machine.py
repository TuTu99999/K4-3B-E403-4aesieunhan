from __future__ import annotations

import pytest

from app.domain.enums import CandidateState
from app.domain.state_machine import (
    InvalidStateTransition,
    TransitionEvent,
    ensure_transition,
)


def test_valid_and_idempotent_transitions() -> None:
    assert ensure_transition(
        CandidateState.WAITING_THRESHOLD,
        CandidateState.CLASSIFYING,
    )
    assert not ensure_transition(
        CandidateState.CLASSIFYING,
        CandidateState.CLASSIFYING,
    )


def test_invalid_transition_is_rejected() -> None:
    with pytest.raises(InvalidStateTransition):
        ensure_transition(CandidateState.WAITING_THRESHOLD, CandidateState.NOTIFIED)


def test_response_reopens_only_after_invalidation() -> None:
    with pytest.raises(InvalidStateTransition, match="response invalidation"):
        ensure_transition(CandidateState.RESPONDED, CandidateState.CLASSIFYING)

    assert ensure_transition(
        CandidateState.RESPONDED,
        CandidateState.CLASSIFYING,
        event=TransitionEvent.RESPONSE_INVALIDATED,
    )


def test_supersede_requires_new_content_version_event() -> None:
    with pytest.raises(InvalidStateTransition, match="content-version"):
        ensure_transition(
            CandidateState.WAITING_THRESHOLD,
            CandidateState.SUPERSEDED,
        )

    assert ensure_transition(
        CandidateState.WAITING_THRESHOLD,
        CandidateState.SUPERSEDED,
        event=TransitionEvent.CONTENT_VERSION_CHANGED,
    )
