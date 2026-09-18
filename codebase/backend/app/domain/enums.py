"""Enums shared by ingestion, classification, persistence, and the UI."""

from enum import Enum, IntEnum


class ActionLabel(IntEnum):
    """Human-action label produced by the classifier."""

    IGNORE = 0
    NORMAL = 1
    URGENT = 2
    REVIEW = 3


class MessageType(str, Enum):
    MESSAGE = "message"
    REPLY = "reply"


class CandidateState(str, Enum):
    WAITING_THRESHOLD = "WAITING_THRESHOLD"
    WAITING_NORMAL = "WAITING_NORMAL"
    CLASSIFYING = "CLASSIFYING"
    CLASSIFICATION_PENDING = "CLASSIFICATION_PENDING"
    NON_ACTIONABLE = "NON_ACTIONABLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    OPEN_NORMAL = "OPEN_NORMAL"
    OPEN_URGENT = "OPEN_URGENT"
    NOTIFIED = "NOTIFIED"
    CLAIMED = "CLAIMED"
    SNOOZED = "SNOOZED"
    RESPONDED = "RESPONDED"
    MANUAL_HANDLED = "MANUAL_HANDLED"
    DISMISSED = "DISMISSED"
    DELETED = "DELETED"
    INACCESSIBLE = "INACCESSIBLE"
    REOPENED = "REOPENED"
    SUPERSEDED = "SUPERSEDED"


class Priority(str, Enum):
    NORMAL = "NORMAL"
    URGENT = "URGENT"


class ResponsePolicy(str, Enum):
    ANY_OTHER_HUMAN = "any_other_human"
    SUPPORT_ROLES_ONLY = "support_roles_only"
    HUMAN_OR_APPROVED_BOT = "human_or_approved_bot"


class FinalRecheckStatus(str, Enum):
    STILL_OPEN = "STILL_OPEN"
    RESPONDED = "RESPONDED"
    DELETED = "DELETED"
    INACCESSIBLE = "INACCESSIBLE"
    CONTENT_VERSION_CHANGED = "CONTENT_VERSION_CHANGED"
