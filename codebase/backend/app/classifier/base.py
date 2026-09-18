"""Provider abstraction and sanitized failure types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.classifier.schema import ClassificationRequest, ClassificationResponse


@dataclass(frozen=True, slots=True)
class ProviderResult:
    response: ClassificationResponse
    latency_ms: int
    token_usage: dict[str, int] = field(default_factory=dict)
    provider_attempts: int = 1
    raw_response: str | None = None


class ClassifierProvider(Protocol):
    model_name: str

    async def classify(self, request: ClassificationRequest) -> ProviderResult: ...


class ClassifierProviderError(RuntimeError):
    """Sanitized provider failure; never contains response body or prompt text."""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        latency_ms: int = 0,
        provider_attempts: int = 1,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.latency_ms = latency_ms
        self.provider_attempts = provider_attempts
        super().__init__(code)


class ClassifierSchemaError(ClassifierProviderError):
    def __init__(self, *, latency_ms: int = 0, provider_attempts: int = 1) -> None:
        super().__init__(
            "INVALID_SCHEMA",
            retryable=True,
            latency_ms=latency_ms,
            provider_attempts=provider_attempts,
        )
