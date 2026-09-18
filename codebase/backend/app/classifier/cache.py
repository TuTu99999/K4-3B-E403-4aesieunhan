"""Classification run persistence and successful-result cache lookup."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classifier.base import ProviderResult
from app.classifier.context_builder import ClassificationEnvelope
from app.classifier.schema import (
    ClassificationIntent,
    ClassificationPriority,
    ClassificationResponse,
)
from app.db.tables import ClassificationRun


class ClassificationCache:
    def get_success(
        self,
        session: Session,
        cache_key: str,
    ) -> tuple[ClassificationRun, ClassificationResponse] | None:
        run = session.scalar(
            select(ClassificationRun)
            .where(
                ClassificationRun.cache_key == cache_key,
                ClassificationRun.status == "SUCCESS",
            )
            .order_by(ClassificationRun.created_at_utc.desc(), ClassificationRun.id.desc())
        )
        if run is None:
            return None
        response = ClassificationResponse(
            intent=ClassificationIntent(run.intent),
            priority=(ClassificationPriority(run.priority) if run.priority else None),
            confidence=run.confidence,
        )
        return run, response

    def add_success(
        self,
        session: Session,
        envelope: ClassificationEnvelope,
        result: ProviderResult,
        *,
        model_name: str,
        status: str = "SUCCESS",
    ) -> ClassificationRun:
        run = ClassificationRun(
            candidate_id=envelope.candidate_id,
            content_version=envelope.content_version,
            prompt_version=envelope.request.prompt_version,
            model_name=model_name,
            cache_key=envelope.cache_key,
            request_hash=envelope.request_hash,
            context_hash=envelope.context_hash,
            intent=result.response.intent.value,
            priority=result.response.priority.value if result.response.priority else None,
            confidence=result.response.confidence,
            status=status,
            latency_ms=result.latency_ms,
            provider_attempts=result.provider_attempts,
            token_usage_json=json.dumps(
                result.token_usage,
                sort_keys=True,
                separators=(",", ":"),
            ),
            created_at_utc=datetime.now(timezone.utc),
        )
        session.add(run)
        session.flush()
        return run

    def add_error(
        self,
        session: Session,
        envelope: ClassificationEnvelope,
        *,
        model_name: str,
        error_code: str,
        latency_ms: int,
        provider_attempts: int,
    ) -> ClassificationRun:
        run = ClassificationRun(
            candidate_id=envelope.candidate_id,
            content_version=envelope.content_version,
            prompt_version=envelope.request.prompt_version,
            model_name=model_name,
            cache_key=envelope.cache_key,
            request_hash=envelope.request_hash,
            context_hash=envelope.context_hash,
            status="ERROR",
            error_code=error_code,
            latency_ms=latency_ms,
            provider_attempts=provider_attempts,
            token_usage_json="{}",
            created_at_utc=datetime.now(timezone.utc),
        )
        session.add(run)
        session.flush()
        return run
