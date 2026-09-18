"""Cheap deterministic checks that run before any model call."""

from __future__ import annotations

from app.domain.candidate import CandidateMessage, EligibilityDecision

RULE_VERSION = "rules-v1"
_SUPPORTED_MESSAGE_TYPES = frozenset({"message", "reply"})


def evaluate_eligibility(
    message: CandidateMessage,
    *,
    channel_enabled: bool,
) -> EligibilityDecision:
    checks = {
        "channel_enabled": channel_enabled,
        "not_bot": not message.is_bot,
        "not_webhook": not message.is_webhook,
        "not_system": not message.is_system,
        "student_author": message.author_role_type == "student",
        "supported_message_type": message.message_type in _SUPPORTED_MESSAGE_TYPES,
        "has_text_or_attachment": bool(message.content_redacted.strip())
        or message.attachment_count > 0,
        "not_deleted": not message.is_deleted,
    }
    reasons = tuple(name.upper() for name, passed in checks.items() if not passed)
    return EligibilityDecision(
        eligible=all(checks.values()),
        checks=checks,
        reason_codes=reasons,
    )
