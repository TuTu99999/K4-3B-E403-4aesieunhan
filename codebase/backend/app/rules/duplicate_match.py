"""Strict exact-duplicate matching; fuzzy closure is intentionally out of scope."""

from __future__ import annotations

from datetime import timedelta

from app.domain.candidate import CandidateMessage


def find_strict_duplicates(
    candidate: CandidateMessage,
    messages: tuple[CandidateMessage, ...] | list[CandidateMessage],
    *,
    window: timedelta = timedelta(minutes=10),
) -> tuple[CandidateMessage, ...]:
    matches: list[CandidateMessage] = []
    for other in messages:
        if other.message_key == candidate.message_key or other.is_deleted:
            continue
        if other.author_id_hash != candidate.author_id_hash:
            continue
        if other.channel_id != candidate.channel_id:
            continue
        if other.conversation_scope != candidate.conversation_scope:
            continue
        if other.content_hash != candidate.content_hash:
            continue
        if abs(other.effective_at_utc - candidate.effective_at_utc) > window:
            continue
        matches.append(other)
    return tuple(sorted(matches, key=lambda item: (item.effective_at_utc, item.message_key)))
