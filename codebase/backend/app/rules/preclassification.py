"""Threshold and fast-lane decision before classification."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.candidate import CandidateMessage, PreclassificationDecision
from app.domain.enums import CandidateState
from app.rules.risk_hints import detect_risk_hints


def decide_preclassification_state(
    message: CandidateMessage,
    *,
    now: datetime,
    t_fast_minutes: int,
    t_normal_minutes: int,
) -> PreclassificationDecision:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if t_fast_minutes < 0 or t_normal_minutes <= 0 or t_fast_minutes > t_normal_minutes:
        raise ValueError("thresholds must satisfy 0 <= T_fast <= T_normal")

    age = max(int((now - message.effective_at_utc).total_seconds()), 0)
    fast_at = message.effective_at_utc + timedelta(minutes=t_fast_minutes)
    normal_at = message.effective_at_utc + timedelta(minutes=t_normal_minutes)
    hints = detect_risk_hints(message.content_redacted)

    if message.is_attachment_only and now >= normal_at:
        return PreclassificationDecision(
            CandidateState.NEEDS_REVIEW,
            normal_at,
            hints,
            age,
            "ATTACHMENT_ONLY_REVIEW",
        )
    if hints and now >= fast_at:
        return PreclassificationDecision(
            CandidateState.CLASSIFYING,
            fast_at,
            hints,
            age,
            "FAST_LANE_DUE",
        )
    if now >= normal_at:
        return PreclassificationDecision(
            CandidateState.CLASSIFYING,
            normal_at,
            hints,
            age,
            "NORMAL_THRESHOLD_DUE",
        )
    return PreclassificationDecision(
        CandidateState.WAITING_THRESHOLD,
        fast_at if hints else normal_at,
        hints,
        age,
        "WAITING_FOR_THRESHOLD",
    )
