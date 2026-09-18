from __future__ import annotations

import pytest

from app.rules.eligibility import evaluate_eligibility
from tests.helpers import candidate_message


def test_student_text_message_is_eligible() -> None:
    decision = evaluate_eligibility(candidate_message(), channel_enabled=True)

    assert decision.eligible
    assert decision.reason_codes == ()


@pytest.mark.parametrize(
    ("override", "failed_check"),
    [
        ({"is_bot": True}, "NOT_BOT"),
        ({"is_webhook": True}, "NOT_WEBHOOK"),
        ({"is_system": True}, "NOT_SYSTEM"),
        ({"author_role_type": "support"}, "STUDENT_AUTHOR"),
        ({"message_type": "reaction"}, "SUPPORTED_MESSAGE_TYPE"),
        ({"content_redacted": ""}, "HAS_TEXT_OR_ATTACHMENT"),
        ({"deleted_at_utc": candidate_message().created_at_utc}, "NOT_DELETED"),
    ],
)
def test_ineligible_sources_are_excluded(override: dict[str, object], failed_check: str) -> None:
    decision = evaluate_eligibility(
        candidate_message(**override),
        channel_enabled=True,
    )

    assert not decision.eligible
    assert failed_check in decision.reason_codes


def test_attachment_only_message_stays_eligible_for_human_review() -> None:
    decision = evaluate_eligibility(
        candidate_message(content_redacted="", attachment_count=1),
        channel_enabled=True,
    )

    assert decision.eligible


def test_reply_can_be_a_candidate_itself() -> None:
    decision = evaluate_eligibility(
        candidate_message(message_type="reply", reply_to_key="G1:C1:M00000"),
        channel_enabled=True,
    )

    assert decision.eligible
