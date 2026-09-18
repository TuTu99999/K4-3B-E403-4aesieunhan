"""Canonical Pydantic models for private and synthetic CSV fixtures."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import ActionLabel, MessageType


MESSAGE_COLUMNS = (
    "msg_id",
    "guild",
    "channel",
    "author",
    "is_bot",
    "msg_type",
    "created_at_vn",
    "reply_to",
    "mentions_bot",
    "n_attachments",
    "n_chars",
    "content",
)
LABELED_COLUMNS = (*MESSAGE_COLUMNS, "label", "label_reason")


class MessageRow(BaseModel):
    """One normalized Discord message row."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    msg_id: str = Field(min_length=1)
    guild: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    author: str = Field(min_length=1)
    is_bot: bool
    msg_type: MessageType
    created_at_vn: datetime
    reply_to: str | None = None
    mentions_bot: bool
    n_attachments: int = Field(ge=0)
    n_chars: int = Field(ge=0)
    content: str = Field(min_length=1)

    @field_validator("msg_id", "guild", "channel", "author", mode="before")
    @classmethod
    def strip_identifier(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("reply_to", mode="before")
    @classmethod
    def normalize_reply_to(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("reply_to")
    @classmethod
    def validate_reply_to(cls, value: str | None) -> str | None:
        if value is not None and not (
            value.startswith("M") and len(value) == 6 and value[1:].isdigit()
        ):
            raise ValueError("reply_to must use the anonymized M##### format")
        return value

    @field_validator("created_at_vn", mode="before")
    @classmethod
    def parse_created_at(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            return value

        raw = value.strip()
        for date_format in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(raw, date_format)
            except ValueError:
                continue
        raise ValueError(
            "created_at_vn must match YYYY-MM-DD HH:MM or DD/MM/YYYY HH:MM"
        )

    @property
    def offline_key(self) -> str:
        return f"{self.guild}:{self.channel}:{self.msg_id}"


class LabeledRow(MessageRow):
    """A message with a human-reviewed dataset label."""

    label: ActionLabel
    label_reason: str | None = None

    @field_validator("label", mode="before")
    @classmethod
    def parse_dataset_label(cls, value: Any) -> ActionLabel:
        try:
            numeric = int(value)
            label = ActionLabel(numeric)
        except (TypeError, ValueError) as exc:
            raise ValueError("label must be one of 0, 1, or 2") from exc
        if label is ActionLabel.REVIEW:
            raise ValueError("label 3 (REVIEW) is runtime-only and cannot appear in a dataset")
        return label

    @field_validator("label_reason", mode="before")
    @classmethod
    def normalize_label_reason(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value
