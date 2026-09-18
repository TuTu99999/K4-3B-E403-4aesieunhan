from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.migrations import upgrade_database
from app.db.session import create_database_engine, create_session_factory
from app.db.tables import ChannelConfig, MessageHead, MessageSnapshot
from app.ingestion.csv_source import CsvMessageSource
from app.ingestion.normalizer import MessageNormalizer
from app.worker.lease import ChannelLeaseManager
from app.worker.scanner import ChannelScanner


@pytest.mark.private_data
def test_full_private_csv_import_is_idempotent(tmp_path) -> None:
    raw_path = os.getenv("PRIVATE_MESSAGES_CSV")
    if not raw_path or not Path(raw_path).is_file():
        pytest.skip("PRIVATE_MESSAGES_CSV is not configured")

    source = CsvMessageSource(raw_path)
    database_path = (tmp_path / "private-import.db").as_posix()
    engine = create_database_engine(f"sqlite:///{database_path}")
    upgrade_database(engine)
    sessions = create_session_factory(engine)
    scanner = ChannelScanner(
        sessions,
        MessageNormalizer("private-integration-test-salt"),
        ChannelLeaseManager(sessions),
        page_size=37,
    )

    config_ids: list[int] = []
    with sessions.begin() as session:
        for channel_ref in source.channel_refs:
            guild_id, channel_id = channel_ref.split(":", 1)
            config = ChannelConfig(
                guild_id=guild_id,
                channel_id=channel_id,
                enabled=True,
                source_type="csv",
            )
            session.add(config)
            session.flush()
            config_ids.append(config.id)

    for config_id in config_ids:
        first = asyncio.run(scanner.scan(config_id, source, owner="private-test-a"))
        second = asyncio.run(scanner.scan(config_id, source, owner="private-test-b"))
        assert first.status == second.status == "SUCCESS"
        assert second.records_seen == 0

    with sessions() as session:
        snapshot_count = session.scalar(select(func.count()).select_from(MessageSnapshot))
        head_count = session.scalar(select(func.count()).select_from(MessageHead))

    assert snapshot_count == 1092
    # The real export contains two repeated canonical keys with distinct content versions.
    assert head_count == 1090
