"""Strict classifier input/output contracts."""

from __future__ import annotations

import hashlib
import json
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClassificationIntent(str, Enum):
    SUPPORT_QUESTION = "SUPPORT_QUESTION"
    NON_ACTIONABLE = "NON_ACTIONABLE"
    UNCERTAIN = "UNCERTAIN"


class ClassificationPriority(str, Enum):
    NORMAL = "NORMAL"
    URGENT = "URGENT"


class ClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str
    context_before: tuple[str, ...] = Field(default=(), max_length=3)
    context_after: tuple[str, ...] = Field(default=(), max_length=3)
    age_minutes: int = Field(ge=0)
    has_attachment: bool
    risk_hints: tuple[str, ...] = ()
    prompt_version: str = Field(min_length=1, max_length=64)

    def canonical_hash(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ClassificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    intent: ClassificationIntent
    priority: ClassificationPriority | None
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_priority_combination(self) -> ClassificationResponse:
        if self.intent is ClassificationIntent.SUPPORT_QUESTION and self.priority is None:
            raise ValueError("SUPPORT_QUESTION requires priority")
        if self.intent is not ClassificationIntent.SUPPORT_QUESTION and self.priority is not None:
            raise ValueError("priority must be null unless intent is SUPPORT_QUESTION")
        return self
