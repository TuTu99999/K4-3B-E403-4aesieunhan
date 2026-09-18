from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.classifier.base import ClassifierProviderError, ClassifierSchemaError, ProviderResult
from app.classifier.context_builder import ClassificationContextBuilder
from app.classifier.schema import (
    ClassificationIntent,
    ClassificationPriority,
    ClassificationResponse,
)
from app.classifier.service import ClassifierService
from app.db.migrations import upgrade_database
from app.db.session import create_database_engine, create_session_factory
from app.db.tables import CandidateRecord, ChannelConfig, ClassificationRun
from app.domain.enums import CandidateState
from app.ingestion.base import SourceMessage
from app.ingestion.normalizer import MessageNormalizer
from app.rules.engine import CandidateRuleEngine
from app.worker.lease import ChannelLeaseManager
from app.worker.scanner import ChannelScanner

NOW = datetime(2026, 9, 18, 4, tzinfo=timezone.utc)


class FakeProvider:
    model_name = "fake-model"

    def __init__(self, outcomes) -> None:
        self.outcomes = deque(outcomes)
        self.calls = 0

    async def classify(self, request):
        del request
        self.calls += 1
        outcome = self.outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return ProviderResult(outcome, latency_ms=12, token_usage={"total_tokens": 9})


class GatedProvider(FakeProvider):
    def __init__(self, outcome, started: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__([outcome])
        self.started = started
        self.release = release

    async def classify(self, request):
        self.started.set()
        await self.release.wait()
        return await super().classify(request)


def response(intent, priority, confidence=0.95) -> ClassificationResponse:
    return ClassificationResponse(intent=intent, priority=priority, confidence=confidence)


def make_runtime(tmp_path):
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'classifier.db').as_posix()}")
    upgrade_database(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        config = ChannelConfig(
            guild_id="G1",
            channel_id="C1",
            enabled=True,
            source_type="csv",
            t_fast_minutes=10,
            t_normal_minutes=60,
        )
        session.add(config)
        session.flush()
        config_id = config.id
    scanner = ChannelScanner(
        sessions,
        MessageNormalizer("classifier-test-salt"),
        ChannelLeaseManager(sessions),
    )
    rules = CandidateRuleEngine(sessions)
    return sessions, scanner, rules, config_id


def message(message_id: str, **overrides) -> SourceMessage:
    values = {
        "source": "csv",
        "guild_id": "G1",
        "channel_id": "C1",
        "message_id": message_id,
        "author_id": "student-a",
        "message_type": "message",
        "content": "Em cần hỗ trợ bài học",
        "created_at_utc": NOW - timedelta(minutes=70),
    }
    values.update(overrides)
    return SourceMessage.model_validate(values)


def prepare_candidate(tmp_path, **message_overrides):
    sessions, scanner, rules, config_id = make_runtime(tmp_path)
    source = message("M1", **message_overrides)
    scanner.ingest_event(config_id, source)
    rules.evaluate_channel(config_id, now=NOW)
    with sessions() as session:
        candidate = session.scalar(select(CandidateRecord))
        assert candidate is not None
        candidate_id = candidate.id
    return sessions, scanner, rules, config_id, candidate_id


def stored_candidate(sessions, candidate_id: str) -> CandidateRecord:
    with sessions() as session:
        candidate = session.get(CandidateRecord, candidate_id)
        assert candidate is not None
        session.expunge(candidate)
        return candidate


def test_service_maps_confidence_and_fast_lane_normal(tmp_path) -> None:
    sessions, _, _, _, candidate_id = prepare_candidate(
        tmp_path,
        created_at_utc=NOW - timedelta(minutes=15),
        content="Em không đăng nhập được tài khoản",
    )
    normal = response(
        ClassificationIntent.SUPPORT_QUESTION,
        ClassificationPriority.NORMAL,
    )
    provider = FakeProvider([normal])

    result = asyncio.run(
        ClassifierService(sessions, provider).classify_candidate(candidate_id, now=NOW)
    )
    stored = stored_candidate(sessions, candidate_id)

    assert result.state is CandidateState.WAITING_NORMAL
    assert stored.priority == "NORMAL"
    assert stored.eligible_at_utc == NOW + timedelta(minutes=45)


def test_service_sends_low_confidence_to_review(tmp_path) -> None:
    sessions, _, _, _, candidate_id = prepare_candidate(tmp_path)
    uncertain_normal = response(
        ClassificationIntent.SUPPORT_QUESTION,
        ClassificationPriority.NORMAL,
        confidence=0.69,
    )

    result = asyncio.run(
        ClassifierService(sessions, FakeProvider([uncertain_normal])).classify_candidate(
            candidate_id, now=NOW
        )
    )

    assert result.state is CandidateState.NEEDS_REVIEW


def test_schema_error_retries_once_and_success_is_cached(tmp_path) -> None:
    sessions, _, _, _, candidate_id = prepare_candidate(tmp_path)
    urgent = response(
        ClassificationIntent.SUPPORT_QUESTION,
        ClassificationPriority.URGENT,
    )
    provider = FakeProvider([ClassifierSchemaError(), urgent])
    service = ClassifierService(sessions, provider, schema_retry_limit=1)

    first = asyncio.run(service.classify_candidate(candidate_id, now=NOW))
    with sessions.begin() as session:
        candidate = session.get(CandidateRecord, candidate_id)
        assert candidate is not None
        candidate.state = CandidateState.CLASSIFYING.value
    second = asyncio.run(service.classify_candidate(candidate_id, now=NOW))

    assert first.state is CandidateState.OPEN_URGENT
    assert second.cache_hit
    assert provider.calls == 2
    with sessions() as session:
        statuses = session.scalars(select(ClassificationRun.status)).all()
    assert statuses.count("ERROR") == statuses.count("SUCCESS") == 1


def test_provider_failure_becomes_pending_without_cache_success(tmp_path) -> None:
    sessions, _, _, _, candidate_id = prepare_candidate(tmp_path)
    failure = ClassifierProviderError("PROVIDER_TIMEOUT", retryable=True, provider_attempts=3)

    result = asyncio.run(
        ClassifierService(sessions, FakeProvider([failure])).classify_candidate(
            candidate_id, now=NOW
        )
    )

    assert result.state is CandidateState.CLASSIFICATION_PENDING
    assert result.error_code == "PROVIDER_TIMEOUT"
    with sessions() as session:
        successes = session.scalar(
            select(func.count()).select_from(ClassificationRun).where(
                ClassificationRun.status == "SUCCESS"
            )
        )
    assert successes == 0


def test_late_provider_result_does_not_overwrite_responded_state(tmp_path) -> None:
    sessions, _, _, _, candidate_id = prepare_candidate(tmp_path)

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        provider = GatedProvider(
            response(ClassificationIntent.SUPPORT_QUESTION, ClassificationPriority.URGENT),
            started,
            release,
        )
        task = asyncio.create_task(
            ClassifierService(sessions, provider).classify_candidate(candidate_id, now=NOW)
        )
        await started.wait()
        with sessions.begin() as session:
            candidate = session.get(CandidateRecord, candidate_id)
            assert candidate is not None
            candidate.state = CandidateState.RESPONDED.value
        release.set()
        return await task

    result = asyncio.run(scenario())

    assert result.stale
    assert result.state is CandidateState.RESPONDED
    assert stored_candidate(sessions, candidate_id).state == CandidateState.RESPONDED.value


def test_context_is_scoped_redacted_bounded_and_cache_versioned(tmp_path) -> None:
    sessions, scanner, rules, config_id = make_runtime(tmp_path)
    for index in range(4):
        scanner.ingest_event(
            config_id,
            message(
                f"B{index}",
                author_id=f"student-{index}",
                content=f"before {index} mail{index}@example.com",
                created_at_utc=NOW - timedelta(minutes=75 - index),
            ),
        )
    target = message("TARGET", content="Em cần slide?", created_at_utc=NOW - timedelta(minutes=70))
    scanner.ingest_event(config_id, target)
    for index in range(4):
        scanner.ingest_event(
            config_id,
            message(
                f"A{index}",
                author_id=f"other-{index}",
                content=f"after {index}",
                created_at_utc=NOW - timedelta(minutes=69 - index),
            ),
        )
    scanner.ingest_event(
        config_id,
        message(
            "THREAD",
            thread_id="different-thread",
            content="must not enter context",
            created_at_utc=NOW - timedelta(minutes=68),
        ),
    )
    rules.evaluate_channel(config_id, now=NOW)
    with sessions() as session:
        candidate = session.scalar(
            select(CandidateRecord).where(CandidateRecord.message_key == target.message_key)
        )
        assert candidate is not None
        builder = ClassificationContextBuilder(context_limit=3, payload_max_chars=500)
        first = builder.build(session, candidate, model_name="model-a", now=NOW)
        other_model = builder.build(session, candidate, model_name="model-b", now=NOW)

    assert len(first.request.context_before) == len(first.request.context_after) == 3
    assert all("@example.com" not in text for text in first.request.context_before)
    assert "must not enter context" not in str(first.request)
    assert first.cache_key != other_model.cache_key
    assert first.request_hash == first.request.canonical_hash()
