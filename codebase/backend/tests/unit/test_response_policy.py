from __future__ import annotations

from app.domain.enums import ResponsePolicy
from app.rules.response_policy import evaluate_direct_response
from tests.helpers import candidate_message


def reply(**overrides: object):
    values: dict[str, object] = {
        "snapshot_id": 2,
        "message_key": "G1:C1:M00002",
        "content_version": "v2",
        "author_id_hash": "author-b",
        "message_type": "reply",
        "reply_to_key": "G1:C1:M00001",
    }
    values.update(overrides)
    return candidate_message(**values)


def test_other_human_direct_reply_closes_under_default_policy() -> None:
    result = evaluate_direct_response(
        candidate_message(),
        reply(),
        ResponsePolicy.ANY_OTHER_HUMAN,
    )

    assert result.responded
    assert result.evidence_type == "DIRECT_REPLY"


def test_self_reply_does_not_close() -> None:
    result = evaluate_direct_response(
        candidate_message(),
        reply(author_id_hash="author-a"),
        ResponsePolicy.ANY_OTHER_HUMAN,
    )

    assert not result.responded
    assert result.reason_code == "SELF_REPLY"


def test_support_only_policy_rejects_peer_and_accepts_support() -> None:
    candidate = candidate_message()

    peer = evaluate_direct_response(
        candidate,
        reply(author_role_type="student"),
        ResponsePolicy.SUPPORT_ROLES_ONLY,
    )
    support = evaluate_direct_response(
        candidate,
        reply(author_role_type="support"),
        ResponsePolicy.SUPPORT_ROLES_ONLY,
    )

    assert not peer.responded
    assert support.responded


def test_only_approved_bot_is_accepted_by_bot_policy() -> None:
    candidate = candidate_message()
    plain_bot = reply(is_bot=True, author_role_type="bot")
    approved_bot = reply(is_bot=True, author_role_type="approved_bot")

    assert not evaluate_direct_response(
        candidate, plain_bot, ResponsePolicy.HUMAN_OR_APPROVED_BOT
    ).responded
    assert evaluate_direct_response(
        candidate, approved_bot, ResponsePolicy.HUMAN_OR_APPROVED_BOT
    ).responded
    assert not evaluate_direct_response(
        candidate, approved_bot, ResponsePolicy.ANY_OTHER_HUMAN
    ).responded


def test_deleted_or_nearby_reply_does_not_close() -> None:
    candidate = candidate_message()

    deleted = evaluate_direct_response(
        candidate,
        reply(deleted_at_utc=candidate.created_at_utc),
        ResponsePolicy.ANY_OTHER_HUMAN,
    )
    nearby = evaluate_direct_response(
        candidate,
        reply(reply_to_key=None),
        ResponsePolicy.ANY_OTHER_HUMAN,
    )

    assert not deleted.responded
    assert not nearby.responded
