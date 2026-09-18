"""Shared domain contracts."""

from app.domain.enums import ActionLabel, CandidateState, MessageType
from app.domain.models import LabeledRow, MessageRow

__all__ = [
    "ActionLabel",
    "CandidateState",
    "LabeledRow",
    "MessageRow",
    "MessageType",
]
