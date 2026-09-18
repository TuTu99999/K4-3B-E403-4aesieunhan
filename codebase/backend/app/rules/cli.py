"""CLI for deterministic candidate generation on the durable message store."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db.migrations import upgrade_database
from app.db.session import create_database_engine, create_session_factory
from app.db.tables import CandidateRecord, ChannelConfig
from app.rules.engine import CandidateRuleEngine


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic eligibility and response rules."
    )
    parser.add_argument("--database-url", help="Override DATABASE_URL for this run")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    engine = create_database_engine(args.database_url or settings.database_url)
    upgrade_database(engine)
    sessions = create_session_factory(engine)
    with sessions() as session:
        config_ids = session.scalars(
            select(ChannelConfig.id)
            .where(ChannelConfig.enabled.is_(True))
            .order_by(ChannelConfig.id)
        ).all()
    if not config_ids:
        raise SystemExit("Phase 2 rule evaluation failed: no enabled channel configs")

    evaluator = CandidateRuleEngine(sessions)
    now = datetime.now(timezone.utc)
    summaries = [
        evaluator.evaluate_channel(config_id, now=now) for config_id in config_ids
    ]
    with sessions() as session:
        states = Counter(session.scalars(select(CandidateRecord.state)).all())
    engine.dispose()

    print("Phase 2 rule evaluation completed.")
    print(f"Messages evaluated: {sum(item.messages_evaluated for item in summaries)}")
    print(f"New candidates: {sum(item.candidates_created for item in summaries)}")
    print(f"State changes: {sum(item.state_changes for item in summaries)}")
    print(f"New audits: {sum(item.audits_created for item in summaries)}")
    print(f"Candidate states: {dict(sorted(states.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
