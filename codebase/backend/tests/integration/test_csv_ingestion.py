from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, inspect, select

from app.db.migrations import downgrade_database, upgrade_database
from app.db.repositories import MessageStore
from app.db.session import create_database_engine, create_session_factory
from app.db.tables import ChannelConfig, MessageHead, MessageSnapshot, WorkerCursor
from app.ingestion.base import Page, SourceMessage, SourcePermissionDenied
from app.ingestion.csv_source import CsvMessageSource
from app.ingestion.normalizer import MessageNormalizer
from app.worker.lease import ChannelLeaseManager
from app.worker.scanner import ChannelScanner
from tests.helpers import message_values, write_messages


def make_runtime(tmp_path, *, store: MessageStore | None = None):
    database_path = (tmp_path / "phase1.db").as_posix()
    engine = create_database_engine(f"sqlite:///{database_path}")
    upgrade_database(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        config = ChannelConfig(
            guild_id="TEST-GUILD",
            channel_id="channel_test",
            enabled=True,
            source_type="csv",
        )
        session.add(config)
        session.flush()
        config_id = config.id
    leases = ChannelLeaseManager(sessions)
    scanner = ChannelScanner(
        sessions,
        MessageNormalizer("phase-one-test-salt"),
        leases,
        page_size=2,
        store=store,
    )
    return engine, sessions, scanner, config_id, leases


def event_message(**overrides: object) -> SourceMessage:
    values: dict[str, object] = {
        "source": "csv",
        "guild_id": "TEST-GUILD",
        "channel_id": "channel_test",
        "message_id": "M00001",
        "author_id": "D0001",
        "message_type": "message",
        "content": "Nội dung gốc",
        "created_at_utc": datetime(2026, 9, 18, 2, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SourceMessage.model_validate(values)


def test_csv_scan_is_idempotent_and_restart_safe(tmp_path) -> None:
    csv_path = write_messages(
        tmp_path / "messages.csv",
        [
            message_values(msg_id="M00001"),
            message_values(msg_id="M00002", msg_type="reply", reply_to="M00001"),
            message_values(msg_id="M00003", created_at_vn="2026-09-18 09:01"),
        ],
    )
    source = CsvMessageSource(csv_path)
    _, sessions, scanner, config_id, leases = make_runtime(tmp_path)

    first = asyncio.run(scanner.scan(config_id, source, owner="worker-a"))
    restarted = ChannelScanner(
        sessions,
        MessageNormalizer("phase-one-test-salt"),
        leases,
        page_size=1,
    )
    second = asyncio.run(restarted.scan(config_id, source, owner="worker-b"))

    with sessions() as session:
        snapshots = session.scalar(select(func.count()).select_from(MessageSnapshot))
        heads = session.scalar(select(func.count()).select_from(MessageHead))
        reply = session.scalar(
            select(MessageSnapshot).where(MessageSnapshot.message_id == "M00002")
        )
        cursor = session.get(WorkerCursor, config_id)

    assert first.records_seen == 3
    assert first.snapshots_created == 3
    assert second.records_seen == 0
    assert snapshots == heads == 3
    assert reply is not None and reply.reply_to_key.endswith(":M00001")
    assert cursor is not None and cursor.last_message_id is not None


def test_edit_delete_and_old_event_preserve_append_only_history(tmp_path) -> None:
    _, sessions, scanner, config_id, _ = make_runtime(tmp_path)
    created = event_message()
    edited = event_message(
        content="Nội dung đã sửa",
        edited_at_utc=created.created_at_utc + timedelta(minutes=2),
    )
    deleted = event_message(
        content="Nội dung đã sửa",
        edited_at_utc=edited.edited_at_utc,
        deleted_at_utc=created.created_at_utc + timedelta(minutes=3),
    )
    late_old_edit = event_message(
        content="Sự kiện cũ tới muộn",
        edited_at_utc=created.created_at_utc + timedelta(minutes=1),
    )

    assert scanner.ingest_event(config_id, created)
    assert scanner.ingest_event(config_id, edited)
    assert scanner.ingest_event(config_id, deleted)
    assert not scanner.ingest_event(config_id, deleted)
    assert scanner.ingest_event(config_id, late_old_edit)

    with sessions() as session:
        snapshots = session.scalars(
            select(MessageSnapshot).order_by(MessageSnapshot.effective_at_utc)
        ).all()
        head = session.get(MessageHead, created.message_key)

    assert len(snapshots) == 4
    assert head is not None and head.is_deleted
    deleted_snapshot = next(item for item in snapshots if item.deleted_at_utc is not None)
    assert head.current_content_version == deleted_snapshot.content_version


class FailingStore(MessageStore):
    def __init__(self) -> None:
        self.calls = 0

    def persist(self, session, channel_config_id, message):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("injected database write failure")
        return super().persist(session, channel_config_id, message)


def test_page_transaction_failure_does_not_advance_cursor(tmp_path) -> None:
    csv_path = write_messages(
        tmp_path / "messages.csv",
        [message_values(msg_id="M00001"), message_values(msg_id="M00002")],
    )
    source = CsvMessageSource(csv_path)
    _, sessions, scanner, config_id, _ = make_runtime(tmp_path, store=FailingStore())

    with pytest.raises(RuntimeError, match="injected database"):
        asyncio.run(scanner.scan(config_id, source, owner="worker-a"))

    with sessions() as session:
        snapshots = session.scalar(select(func.count()).select_from(MessageSnapshot))
        cursor = session.get(WorkerCursor, config_id)

    assert snapshots == 0
    assert cursor is not None and cursor.last_message_id is None
    assert cursor.lease_owner is None


def test_only_one_worker_can_hold_channel_lease(tmp_path) -> None:
    _, _, _, config_id, leases = make_runtime(tmp_path)

    assert leases.acquire(config_id, "worker-a", timedelta(minutes=1))
    assert not leases.acquire(config_id, "worker-b", timedelta(minutes=1))
    assert leases.release(config_id, "worker-a")
    assert leases.acquire(config_id, "worker-b", timedelta(minutes=1))


class PermissionDeniedSource:
    source_kind = "csv"
    calls = 0

    async def fetch_after(self, channel_ref, cursor, limit):
        self.calls += 1
        raise SourcePermissionDenied("fixture permission denied")

    async def fetch_message(self, message_key):
        return None

    async def fetch_direct_replies(self, message_key):
        return []


def test_permission_failure_pauses_channel_without_moving_cursor(tmp_path) -> None:
    _, sessions, scanner, config_id, _ = make_runtime(tmp_path)
    source = PermissionDeniedSource()

    first = asyncio.run(scanner.scan(config_id, source, owner="worker-a"))
    second = asyncio.run(scanner.scan(config_id, source, owner="worker-b"))

    with sessions() as session:
        cursor = session.get(WorkerCursor, config_id)

    assert first.status == second.status == "PAUSED_PERMISSION"
    assert source.calls == 1
    assert cursor is not None and cursor.last_message_id is None
    assert cursor.disabled_until is not None


def test_initial_migration_up_and_down(tmp_path) -> None:
    database_path = (tmp_path / "migration.db").as_posix()
    engine = create_database_engine(f"sqlite:///{database_path}")

    upgrade_database(engine)
    assert set(inspect(engine).get_table_names()) == {
        "candidates",
        "channel_configs",
        "classification_runs",
        "message_heads",
        "message_snapshots",
        "rule_audits",
        "worker_cursors",
    }

    downgrade_database(engine)
    assert inspect(engine).get_table_names() == []
