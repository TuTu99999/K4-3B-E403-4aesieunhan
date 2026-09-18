from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.migrations import upgrade_database
from app.db.session import create_database_engine, create_session_factory
from app.db.tables import CandidateRecord, ChannelConfig, RuleAudit
from app.domain.enums import CandidateState, FinalRecheckStatus, ResponsePolicy
from app.ingestion.base import SourceMessage
from app.ingestion.normalizer import MessageNormalizer
from app.rules.engine import CandidateRuleEngine
from app.rules.final_recheck import FinalRechecker
from app.worker.lease import ChannelLeaseManager
from app.worker.scanner import ChannelScanner

NOW = datetime(2026, 9, 18, 4, tzinfo=timezone.utc)


def make_runtime(tmp_path, *, policy: ResponsePolicy = ResponsePolicy.ANY_OTHER_HUMAN):
    database_path = (tmp_path / "rules.db").as_posix()
    engine = create_database_engine(f"sqlite:///{database_path}")
    upgrade_database(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        config = ChannelConfig(
            guild_id="TEST-GUILD",
            channel_id="channel_test",
            enabled=True,
            source_type="csv",
            response_policy=policy.value,
            t_fast_minutes=10,
            t_normal_minutes=60,
        )
        session.add(config)
        session.flush()
        config_id = config.id
    normalizer = MessageNormalizer(
        "phase-two-test-salt",
        support_role_ids=frozenset({"ta-role"}),
        approved_bot_ids=frozenset({"approved-bot"}),
    )
    scanner = ChannelScanner(
        sessions,
        normalizer,
        ChannelLeaseManager(sessions),
    )
    return sessions, scanner, CandidateRuleEngine(sessions), config_id


def message(message_id: str, **overrides: object) -> SourceMessage:
    values: dict[str, object] = {
        "source": "csv",
        "guild_id": "TEST-GUILD",
        "channel_id": "channel_test",
        "message_id": message_id,
        "author_id": "student-a",
        "message_type": "message",
        "content": "Em cần hỗ trợ bài học",
        "created_at_utc": NOW - timedelta(minutes=70),
    }
    values.update(overrides)
    return SourceMessage.model_validate(values)


def candidates_by_key(sessions) -> dict[str, list[CandidateRecord]]:
    with sessions() as session:
        records = session.scalars(select(CandidateRecord)).all()
        result: dict[str, list[CandidateRecord]] = {}
        for record in records:
            session.expunge(record)
            result.setdefault(record.message_key, []).append(record)
        return result


def test_direct_reply_closes_parent_but_reply_can_be_new_candidate(tmp_path) -> None:
    sessions, scanner, engine, config_id = make_runtime(tmp_path)
    question = message("M00001", content="Slide buổi học ở đâu?")
    reply = message(
        "M00002",
        author_id="student-b",
        message_type="reply",
        reply_to_message_id="M00001",
        content="Ở LMS nhé. Còn deadline hôm nay hả?",
        created_at_utc=question.created_at_utc + timedelta(minutes=5),
    )
    support_message = message(
        "M00003",
        author_id="ta-a",
        author_roles=frozenset({"ta-role"}),
    )
    bot_message = message(
        "M00004",
        author_id="approved-bot",
        is_bot=True,
    )
    for item in (question, reply, support_message, bot_message):
        scanner.ingest_event(config_id, item)

    first = engine.evaluate_channel(config_id, now=NOW)
    second = engine.evaluate_channel(config_id, now=NOW)
    records = candidates_by_key(sessions)

    assert records[question.message_key][0].state == CandidateState.RESPONDED.value
    assert records[reply.message_key][0].state == CandidateState.CLASSIFYING.value
    assert support_message.message_key not in records
    assert bot_message.message_key not in records
    assert first.candidates_created == 2
    assert second.candidates_created == second.state_changes == second.audits_created == 0

    with sessions() as session:
        audits = session.scalars(select(RuleAudit.payload_json)).all()
    assert all("Slide buổi học" not in payload for payload in audits)


def test_self_reply_does_not_close_and_exact_duplicate_can_inherit_response(tmp_path) -> None:
    sessions, scanner, engine, config_id = make_runtime(tmp_path)
    self_question = message("M00001", content="Em bị lỗi bài tập")
    self_reply = message(
        "M00002",
        author_id="student-a",
        message_type="reply",
        reply_to_message_id="M00001",
        content="Em bổ sung ảnh lỗi",
    )
    duplicate_a = message("M00003", content="Cho em xin slide")
    duplicate_b = message(
        "M00004",
        content="Cho em xin slide",
        created_at_utc=duplicate_a.created_at_utc + timedelta(minutes=3),
    )
    duplicate_reply = message(
        "M00005",
        author_id="student-b",
        message_type="reply",
        reply_to_message_id="M00004",
        content="Slide ở LMS nhé",
        created_at_utc=duplicate_b.created_at_utc + timedelta(minutes=1),
    )
    for item in (self_question, self_reply, duplicate_a, duplicate_b, duplicate_reply):
        scanner.ingest_event(config_id, item)

    engine.evaluate_channel(config_id, now=NOW)
    records = candidates_by_key(sessions)

    assert records[self_question.message_key][0].state == CandidateState.CLASSIFYING.value
    inherited = records[duplicate_a.message_key][0]
    assert inherited.state == CandidateState.RESPONDED.value
    assert inherited.response_evidence_type == "DUPLICATE_DIRECT_REPLY"
    assert records[duplicate_b.message_key][0].state == CandidateState.RESPONDED.value


def test_edit_resets_timer_and_delete_closes_candidate(tmp_path) -> None:
    sessions, scanner, engine, config_id = make_runtime(tmp_path)
    original = message("M00001")
    scanner.ingest_event(config_id, original)
    engine.evaluate_channel(config_id, now=NOW)

    edited = message(
        "M00001",
        content="Nội dung vừa chỉnh sửa",
        edited_at_utc=NOW - timedelta(minutes=5),
    )
    scanner.ingest_event(config_id, edited)
    engine.evaluate_channel(config_id, now=NOW)
    versions = candidates_by_key(sessions)[original.message_key]

    assert {record.state for record in versions} == {
        CandidateState.SUPERSEDED.value,
        CandidateState.WAITING_THRESHOLD.value,
    }

    deleted = message(
        "M00001",
        content="Nội dung vừa chỉnh sửa",
        edited_at_utc=edited.edited_at_utc,
        deleted_at_utc=NOW + timedelta(minutes=1),
    )
    scanner.ingest_event(config_id, deleted)
    engine.evaluate_channel(config_id, now=NOW + timedelta(minutes=1))
    versions = candidates_by_key(sessions)[original.message_key]

    assert any(record.state == CandidateState.DELETED.value for record in versions)


def test_deleted_response_reopens_and_final_recheck_catches_race(tmp_path) -> None:
    sessions, scanner, engine, config_id = make_runtime(tmp_path)
    question = message("M00001")
    scanner.ingest_event(config_id, question)
    engine.evaluate_channel(config_id, now=NOW)
    candidate = candidates_by_key(sessions)[question.message_key][0]

    reply = message(
        "M00002",
        author_id="student-b",
        message_type="reply",
        reply_to_message_id="M00001",
        content="Bạn thử tải lại trang nhé",
    )
    scanner.ingest_event(config_id, reply)
    race_result = FinalRechecker(sessions).check(candidate.id)
    assert race_result.status is FinalRecheckStatus.RESPONDED

    engine.evaluate_channel(config_id, now=NOW)
    parent = candidates_by_key(sessions)[question.message_key][0]
    assert parent.state == CandidateState.RESPONDED.value

    deleted_reply = message(
        "M00002",
        author_id="student-b",
        message_type="reply",
        reply_to_message_id="M00001",
        content="Bạn thử tải lại trang nhé",
        deleted_at_utc=NOW + timedelta(minutes=1),
    )
    scanner.ingest_event(config_id, deleted_reply)
    engine.evaluate_channel(config_id, now=NOW + timedelta(minutes=1))

    reopened = candidates_by_key(sessions)[question.message_key][0]
    assert reopened.state == CandidateState.CLASSIFYING.value


def test_final_recheck_returns_all_source_of_truth_outcomes(tmp_path) -> None:
    sessions, scanner, engine, config_id = make_runtime(tmp_path)
    question = message("M00001")
    scanner.ingest_event(config_id, question)
    engine.evaluate_channel(config_id, now=NOW)
    candidate = candidates_by_key(sessions)[question.message_key][0]
    rechecker = FinalRechecker(sessions)

    assert rechecker.check(candidate.id).status is FinalRecheckStatus.STILL_OPEN

    edited = message(
        "M00001",
        content="Nội dung mới",
        edited_at_utc=NOW + timedelta(minutes=1),
    )
    scanner.ingest_event(config_id, edited)
    assert (
        rechecker.check(candidate.id).status
        is FinalRecheckStatus.CONTENT_VERSION_CHANGED
    )

    deleted = message(
        "M00001",
        content="Nội dung mới",
        edited_at_utc=edited.edited_at_utc,
        deleted_at_utc=NOW + timedelta(minutes=2),
    )
    scanner.ingest_event(config_id, deleted)
    assert rechecker.check(candidate.id).status is FinalRecheckStatus.DELETED

    with sessions.begin() as session:
        config = session.get(ChannelConfig, config_id)
        assert config is not None
        config.enabled = False
    assert rechecker.check(candidate.id).status is FinalRecheckStatus.INACCESSIBLE


def test_rule_tick_preserves_post_classification_state_until_new_evidence(tmp_path) -> None:
    sessions, scanner, engine, config_id = make_runtime(tmp_path)
    question = message("M00001")
    scanner.ingest_event(config_id, question)
    engine.evaluate_channel(config_id, now=NOW)
    candidate = candidates_by_key(sessions)[question.message_key][0]

    with sessions.begin() as session:
        stored = session.get(CandidateRecord, candidate.id)
        assert stored is not None
        stored.state = CandidateState.OPEN_NORMAL.value
        stored.priority = "NORMAL"

    engine.evaluate_channel(config_id, now=NOW + timedelta(minutes=1))
    assert (
        candidates_by_key(sessions)[question.message_key][0].state
        == CandidateState.OPEN_NORMAL.value
    )

    reply = message(
        "M00002",
        author_id="student-b",
        message_type="reply",
        reply_to_message_id="M00001",
        content="Bạn xem trong LMS nhé",
    )
    scanner.ingest_event(config_id, reply)
    engine.evaluate_channel(config_id, now=NOW + timedelta(minutes=2))
    assert (
        candidates_by_key(sessions)[question.message_key][0].state
        == CandidateState.RESPONDED.value
    )
