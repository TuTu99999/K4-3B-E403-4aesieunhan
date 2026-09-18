from __future__ import annotations

import asyncio
import os
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.migrations import upgrade_database
from app.db.session import create_database_engine, create_session_factory
from app.db.tables import CandidateRecord, ChannelConfig, MessageSnapshot, RuleAudit
from app.ingestion.csv_source import CsvMessageSource
from app.ingestion.normalizer import MessageNormalizer
from app.rules.engine import CandidateRuleEngine
from app.worker.lease import ChannelLeaseManager
from app.worker.scanner import ChannelScanner


@pytest.mark.private_data
def test_private_rule_generation_is_reproducible(tmp_path) -> None:
    raw_path = os.getenv("PRIVATE_MESSAGES_CSV")
    if not raw_path or not Path(raw_path).is_file():
        pytest.skip("PRIVATE_MESSAGES_CSV is not configured")

    source = CsvMessageSource(raw_path)
    database_path = (tmp_path / "private-rules.db").as_posix()
    engine = create_database_engine(f"sqlite:///{database_path}")
    upgrade_database(engine)
    sessions = create_session_factory(engine)
    scanner = ChannelScanner(
        sessions,
        MessageNormalizer("private-phase-two-test-salt"),
        ChannelLeaseManager(sessions),
        page_size=41,
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
        result = asyncio.run(scanner.scan(config_id, source, owner="private-rules"))
        assert result.status == "SUCCESS"

    with sessions() as session:
        latest = session.scalar(select(func.max(MessageSnapshot.effective_at_utc)))
    assert latest is not None
    evaluation_time = latest + timedelta(minutes=61)
    rules = CandidateRuleEngine(sessions)

    first_runs = [
        rules.evaluate_channel(config_id, now=evaluation_time)
        for config_id in config_ids
    ]
    second_runs = [
        rules.evaluate_channel(config_id, now=evaluation_time)
        for config_id in config_ids
    ]

    with sessions() as session:
        candidates = session.scalars(select(CandidateRecord)).all()
        audit_count = session.scalar(select(func.count()).select_from(RuleAudit)) or 0
    states = Counter(candidate.state for candidate in candidates)

    assert sum(run.candidates_created for run in first_runs) == len(candidates)
    assert all(run.candidates_created == 0 for run in second_runs)
    assert all(run.state_changes == 0 for run in second_runs)
    assert all(run.audits_created == 0 for run in second_runs)
    assert sum(states.values()) == len(candidates)
    assert audit_count > len(candidates)  # Excluded bot/system decisions are audited too.
    assert len(candidates) == 777
    assert states == {"CLASSIFYING": 616, "RESPONDED": 161}
    assert audit_count == 1090

    print(f"private_candidates={len(candidates)}")
    print(f"private_states={dict(sorted(states.items()))}")
    print(f"private_rule_audits={audit_count}")
