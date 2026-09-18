"""Run bounded classification batches against candidates in durable storage."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter

from sqlalchemy import select

from app.classifier.context_builder import ClassificationContextBuilder
from app.classifier.provider import OpenAICompatibleClassifierProvider
from app.classifier.service import CandidateNotClassifiable, ClassifierService
from app.config import ConfigurationError, get_settings
from app.db.migrations import upgrade_database
from app.db.session import create_database_engine, create_session_factory
from app.db.tables import CandidateRecord
from app.domain.enums import CandidateState

_READY_STATES = (
    CandidateState.CLASSIFYING.value,
    CandidateState.CLASSIFICATION_PENDING.value,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify a bounded batch of unanswered Discord candidates."
    )
    parser.add_argument("--database-url", help="Override DATABASE_URL for this run")
    parser.add_argument("--candidate-id", help="Classify exactly one candidate")
    parser.add_argument("--limit", type=int, default=10, help="Maximum batch size")
    return parser.parse_args()


async def _run(database_url: str, *, candidate_id: str | None, limit: int) -> Counter[str]:
    settings = get_settings()
    api_key, base_url, model = settings.require_classifier_config()
    engine = create_database_engine(database_url)
    upgrade_database(engine)
    sessions = create_session_factory(engine)
    with sessions() as session:
        query = select(CandidateRecord.id).where(CandidateRecord.state.in_(_READY_STATES))
        if candidate_id:
            query = query.where(CandidateRecord.id == candidate_id)
        candidate_ids = session.scalars(
            query.order_by(CandidateRecord.effective_at_utc, CandidateRecord.id).limit(limit)
        ).all()

    if candidate_id and not candidate_ids:
        engine.dispose()
        raise CandidateNotClassifiable(
            "candidate does not exist or is not ready for classification"
        )

    provider = OpenAICompatibleClassifierProvider(
        api_key,
        base_url,
        model,
        timeout_seconds=settings.classifier_timeout_seconds,
        retry_limit=settings.classifier_retry_limit,
    )
    service = ClassifierService(
        sessions,
        provider,
        confidence_threshold=settings.classifier_confidence_threshold,
        schema_retry_limit=settings.classifier_schema_retry_limit,
        context_builder=ClassificationContextBuilder(
            context_limit=settings.classifier_context_limit,
            context_window_minutes=settings.classifier_context_window_minutes,
            payload_max_chars=settings.classifier_payload_max_chars,
        ),
    )
    semaphore = asyncio.Semaphore(settings.classifier_concurrency)

    async def classify(item_id: str):
        async with semaphore:
            return await service.classify_candidate(item_id)

    try:
        results = await asyncio.gather(*(classify(item_id) for item_id in candidate_ids))
    finally:
        await provider.aclose()
        engine.dispose()

    counts = Counter(result.state.value for result in results)
    counts["CACHE_HIT"] = sum(result.cache_hit for result in results)
    counts["STALE"] = sum(result.stale for result in results)
    counts["ERROR"] = sum(result.error_code is not None for result in results)
    counts["PROCESSED"] = len(results)
    return counts


def main() -> int:
    args = _parse_args()
    if args.limit <= 0:
        raise SystemExit("--limit must be positive")
    settings = get_settings()
    try:
        counts = asyncio.run(
            _run(
                args.database_url or settings.database_url,
                candidate_id=args.candidate_id,
                limit=1 if args.candidate_id else args.limit,
            )
        )
    except (ConfigurationError, CandidateNotClassifiable, ValueError) as exc:
        raise SystemExit(f"Phase 3 classification failed: {exc}") from exc

    print("Phase 3 classification completed.")
    print(f"Processed: {counts.pop('PROCESSED', 0)}")
    print(f"Cache hits: {counts.pop('CACHE_HIT', 0)}")
    print(f"Stale results: {counts.pop('STALE', 0)}")
    print(f"Errors pending retry: {counts.pop('ERROR', 0)}")
    print(f"Result states: {dict(sorted(counts.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
