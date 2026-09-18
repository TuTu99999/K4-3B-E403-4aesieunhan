"""Direct-reply validity under configurable community policies."""

from __future__ import annotations

from app.domain.candidate import CandidateMessage, ResponseDecision
from app.domain.enums import ResponsePolicy


def evaluate_direct_response(
    candidate: CandidateMessage,
    reply: CandidateMessage,
    policy: ResponsePolicy,
) -> ResponseDecision:
    if reply.reply_to_key != candidate.message_key:
        return ResponseDecision(False, "NOT_DIRECT_REPLY")
    if reply.is_deleted:
        return ResponseDecision(False, "REPLY_DELETED")
    if reply.is_webhook or reply.is_system:
        return ResponseDecision(False, "UNSUPPORTED_REPLY_SOURCE")
    if reply.author_id_hash == candidate.author_id_hash:
        return ResponseDecision(False, "SELF_REPLY")

    accepted = False
    if policy is ResponsePolicy.ANY_OTHER_HUMAN:
        accepted = not reply.is_bot and reply.author_role_type in {"student", "support"}
    elif policy is ResponsePolicy.SUPPORT_ROLES_ONLY:
        accepted = not reply.is_bot and reply.author_role_type == "support"
    elif policy is ResponsePolicy.HUMAN_OR_APPROVED_BOT:
        accepted = (
            not reply.is_bot and reply.author_role_type in {"student", "support"}
        ) or (reply.is_bot and reply.author_role_type == "approved_bot")

    if not accepted:
        return ResponseDecision(False, "POLICY_REJECTED")
    return ResponseDecision(
        True,
        "VALID_DIRECT_RESPONSE",
        response_key=reply.message_key,
        evidence_type="DIRECT_REPLY",
    )


def find_valid_direct_response(
    candidate: CandidateMessage,
    replies: list[CandidateMessage] | tuple[CandidateMessage, ...],
    policy: ResponsePolicy,
) -> ResponseDecision:
    for reply in sorted(replies, key=lambda item: (item.effective_at_utc, item.message_key)):
        decision = evaluate_direct_response(candidate, reply, policy)
        if decision.responded:
            return decision
    return ResponseDecision(False, "NO_VALID_DIRECT_RESPONSE")
