"""Classifier orchestration, confidence gate, cache, and candidate transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, sessionmaker

from app.classifier.base import (
    ClassifierProvider,
    ClassifierProviderError,
    ClassifierSchemaError,
    ProviderResult,
)
from app.classifier.cache import ClassificationCache
from app.classifier.context_builder import (
    ClassificationContextBuilder,
    ClassificationEnvelope,
)
from app.classifier.schema import (
    ClassificationIntent,
    ClassificationPriority,
    ClassificationResponse,
)
from app.db.tables import CandidateRecord
from app.domain.enums import CandidateState
from app.domain.state_machine import ensure_transition

_CLASSIFIABLE_STATES = frozenset(
    {CandidateState.CLASSIFYING, CandidateState.CLASSIFICATION_PENDING}
)


class CandidateNotClassifiable(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ClassifierServiceResult:
    candidate_id: str
    state: CandidateState
    response: ClassificationResponse | None
    cache_hit: bool
    stale: bool
    error_code: str | None = None
    latency_ms: int = 0
    provider_attempts: int = 0


class ClassifierService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider: ClassifierProvider,
        *,
        confidence_threshold: float = 0.70,
        schema_retry_limit: int = 1,
        context_builder: ClassificationContextBuilder | None = None,
        cache: ClassificationCache | None = None,
    ) -> None:
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be between 0 and 1")
        if schema_retry_limit < 0:
            raise ValueError("schema_retry_limit cannot be negative")
        self._session_factory = session_factory
        self._provider = provider
        self._threshold = confidence_threshold
        self._schema_retry_limit = schema_retry_limit
        self._context_builder = context_builder or ClassificationContextBuilder()
        self._cache = cache or ClassificationCache()

    async def classify_candidate(
        self,
        candidate_id: str,
        *,
        now: datetime | None = None,
    ) -> ClassifierServiceResult:
        evaluation_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._session_factory.begin() as session:
            candidate = self._require_classifiable(session, candidate_id)
            envelope = self._context_builder.build(
                session,
                candidate,
                model_name=self._provider.model_name,
                now=evaluation_time,
            )
            cached = self._cache.get_success(session, envelope.cache_key)
            if cached is not None:
                _, response = cached
                state = self._apply_response(
                    candidate,
                    response,
                    envelope,
                    now=evaluation_time,
                )
                return ClassifierServiceResult(
                    candidate_id,
                    state,
                    response,
                    cache_hit=True,
                    stale=False,
                )

        errors: list[ClassifierProviderError] = []
        result: ProviderResult | None = None
        for schema_attempt in range(self._schema_retry_limit + 1):
            try:
                result = await self._provider.classify(envelope.request)
                break
            except ClassifierSchemaError as exc:
                errors.append(exc)
                if schema_attempt >= self._schema_retry_limit:
                    break
            except ClassifierProviderError as exc:
                errors.append(exc)
                break

        if result is None:
            return self._record_failure(candidate_id, envelope, errors, evaluation_time)
        return self._record_success(
            candidate_id,
            envelope,
            result,
            errors,
            evaluation_time,
        )

    def _record_success(
        self,
        candidate_id: str,
        envelope: ClassificationEnvelope,
        result: ProviderResult,
        errors: list[ClassifierProviderError],
        now: datetime,
    ) -> ClassifierServiceResult:
        with self._session_factory.begin() as session:
            candidate = session.get(CandidateRecord, candidate_id)
            if candidate is None:
                raise LookupError(f"candidate {candidate_id} does not exist")
            for error in errors:
                self._cache.add_error(
                    session,
                    envelope,
                    model_name=self._provider.model_name,
                    error_code=error.code,
                    latency_ms=error.latency_ms,
                    provider_attempts=error.provider_attempts,
                )
            current = CandidateState(candidate.state)
            if current not in _CLASSIFIABLE_STATES:
                self._cache.add_success(
                    session,
                    envelope,
                    result,
                    model_name=self._provider.model_name,
                    status="STALE",
                )
                return ClassifierServiceResult(
                    candidate_id,
                    current,
                    result.response,
                    cache_hit=False,
                    stale=True,
                    latency_ms=result.latency_ms,
                    provider_attempts=result.provider_attempts,
                )

            self._cache.add_success(
                session,
                envelope,
                result,
                model_name=self._provider.model_name,
            )
            state = self._apply_response(
                candidate,
                result.response,
                envelope,
                now=now,
            )
            return ClassifierServiceResult(
                candidate_id,
                state,
                result.response,
                cache_hit=False,
                stale=False,
                latency_ms=result.latency_ms,
                provider_attempts=result.provider_attempts,
            )

    def _record_failure(
        self,
        candidate_id: str,
        envelope: ClassificationEnvelope,
        errors: list[ClassifierProviderError],
        now: datetime,
    ) -> ClassifierServiceResult:
        last_error = errors[-1] if errors else ClassifierProviderError(
            "UNKNOWN_PROVIDER_ERROR", retryable=False
        )
        with self._session_factory.begin() as session:
            candidate = session.get(CandidateRecord, candidate_id)
            if candidate is None:
                raise LookupError(f"candidate {candidate_id} does not exist")
            for error in errors or [last_error]:
                self._cache.add_error(
                    session,
                    envelope,
                    model_name=self._provider.model_name,
                    error_code=error.code,
                    latency_ms=error.latency_ms,
                    provider_attempts=error.provider_attempts,
                )
            current = CandidateState(candidate.state)
            if current in _CLASSIFIABLE_STATES:
                changed = ensure_transition(
                    current,
                    CandidateState.CLASSIFICATION_PENDING,
                )
                if changed:
                    candidate.state = CandidateState.CLASSIFICATION_PENDING.value
                    candidate.version += 1
                    candidate.updated_at_utc = now
                state = CandidateState.CLASSIFICATION_PENDING
                stale = False
            else:
                state = current
                stale = True
            return ClassifierServiceResult(
                candidate_id,
                state,
                response=None,
                cache_hit=False,
                stale=stale,
                error_code=last_error.code,
                latency_ms=last_error.latency_ms,
                provider_attempts=sum(error.provider_attempts for error in errors),
            )

    def _apply_response(
        self,
        candidate: CandidateRecord,
        response: ClassificationResponse,
        envelope: ClassificationEnvelope,
        *,
        now: datetime,
    ) -> CandidateState:
        current = CandidateState(candidate.state)
        target = self._map_state(response, envelope)
        changed = ensure_transition(current, target)
        eligible_at = candidate.effective_at_utc + timedelta(
            minutes=envelope.t_normal_minutes
        )
        fields_changed = any(
            (
                candidate.classification_intent != response.intent.value,
                candidate.priority
                != (response.priority.value if response.priority is not None else None),
                candidate.classification_confidence != response.confidence,
                target is CandidateState.WAITING_NORMAL
                and candidate.eligible_at_utc != eligible_at,
            )
        )
        if changed or fields_changed:
            candidate.state = target.value
            candidate.classification_intent = response.intent.value
            candidate.priority = (
                response.priority.value if response.priority is not None else None
            )
            candidate.classification_confidence = response.confidence
            if target is CandidateState.WAITING_NORMAL:
                candidate.eligible_at_utc = eligible_at
            candidate.version += 1
            candidate.updated_at_utc = now
        return target

    def _map_state(
        self,
        response: ClassificationResponse,
        envelope: ClassificationEnvelope,
    ) -> CandidateState:
        if response.confidence < self._threshold:
            return CandidateState.NEEDS_REVIEW
        if response.intent is ClassificationIntent.UNCERTAIN:
            return CandidateState.NEEDS_REVIEW
        if response.intent is ClassificationIntent.NON_ACTIONABLE:
            return CandidateState.NON_ACTIONABLE
        if response.priority is ClassificationPriority.URGENT:
            return CandidateState.OPEN_URGENT
        if envelope.request.age_minutes >= envelope.t_normal_minutes:
            return CandidateState.OPEN_NORMAL
        return CandidateState.WAITING_NORMAL

    @staticmethod
    def _require_classifiable(
        session: Session,
        candidate_id: str,
    ) -> CandidateRecord:
        candidate = session.get(CandidateRecord, candidate_id)
        if candidate is None:
            raise LookupError(f"candidate {candidate_id} does not exist")
        state = CandidateState(candidate.state)
        if state not in _CLASSIFIABLE_STATES:
            raise CandidateNotClassifiable(
                f"candidate in state {state.value} cannot be classified"
            )
        return candidate
