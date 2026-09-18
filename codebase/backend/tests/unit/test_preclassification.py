from __future__ import annotations

from datetime import timedelta

from app.domain.enums import CandidateState
from app.rules.duplicate_match import find_strict_duplicates
from app.rules.preclassification import decide_preclassification_state
from app.rules.risk_hints import detect_risk_hints
from tests.helpers import candidate_message


def test_risk_hint_enters_fast_lane_but_never_assigns_priority() -> None:
    message = candidate_message(content_redacted="Em không submit được, sắp hết giờ")
    result = decide_preclassification_state(
        message,
        now=message.effective_at_utc + timedelta(minutes=10),
        t_fast_minutes=10,
        t_normal_minutes=60,
    )

    assert result.target_state is CandidateState.CLASSIFYING
    assert "SUBMISSION_BLOCKED" in result.risk_hints
    assert not hasattr(result, "priority")


def test_normal_message_waits_until_normal_threshold() -> None:
    message = candidate_message(content_redacted="Slide buổi học ở đâu ạ")

    waiting = decide_preclassification_state(
        message,
        now=message.effective_at_utc + timedelta(minutes=59),
        t_fast_minutes=10,
        t_normal_minutes=60,
    )
    due = decide_preclassification_state(
        message,
        now=message.effective_at_utc + timedelta(minutes=60),
        t_fast_minutes=10,
        t_normal_minutes=60,
    )

    assert waiting.target_state is CandidateState.WAITING_THRESHOLD
    assert due.target_state is CandidateState.CLASSIFYING


def test_edited_at_resets_age_and_attachment_only_routes_to_review() -> None:
    original = candidate_message()
    edited_at = original.created_at_utc + timedelta(minutes=55)
    edited = candidate_message(
        edited_at_utc=edited_at,
        effective_at_utc=edited_at,
    )
    attachment = candidate_message(content_redacted="", attachment_count=1)

    edited_result = decide_preclassification_state(
        edited,
        now=original.created_at_utc + timedelta(minutes=65),
        t_fast_minutes=10,
        t_normal_minutes=60,
    )
    attachment_result = decide_preclassification_state(
        attachment,
        now=attachment.effective_at_utc + timedelta(minutes=60),
        t_fast_minutes=10,
        t_normal_minutes=60,
    )

    assert edited_result.target_state is CandidateState.WAITING_THRESHOLD
    assert edited_result.effective_age_seconds == 600
    assert attachment_result.target_state is CandidateState.NEEDS_REVIEW


def test_risk_hints_cover_account_session_and_system_failures() -> None:
    hints = detect_risk_hints(
        "Tài khoản bị khóa, không vào được workshop và server down 503"
    )

    assert set(hints) == {
        "ACCOUNT_BLOCKED",
        "SESSION_ACCESS_BLOCKED",
        "SYSTEM_FAILURE",
    }


def test_risk_hint_detects_unstable_live_session_language() -> None:
    assert "SESSION_ACCESS_UNSTABLE" in detect_risk_hints(
        "Em vào mà cứ bị out ra thì phải làm sao ạ"
    )


def test_duplicate_match_requires_every_strict_condition() -> None:
    source = candidate_message()
    valid = candidate_message(
        snapshot_id=2,
        message_key="G1:C1:M00002",
        content_version="v2",
        effective_at_utc=source.effective_at_utc + timedelta(minutes=9),
    )
    wrong_author = candidate_message(
        snapshot_id=3,
        message_key="G1:C1:M00003",
        author_id_hash="other",
    )
    too_late = candidate_message(
        snapshot_id=4,
        message_key="G1:C1:M00004",
        effective_at_utc=source.effective_at_utc + timedelta(minutes=11),
    )
    other_content = candidate_message(
        snapshot_id=5,
        message_key="G1:C1:M00005",
        content_hash="other-content",
    )

    matches = find_strict_duplicates(
        source,
        [valid, wrong_author, too_late, other_content],
    )

    assert matches == (valid,)
