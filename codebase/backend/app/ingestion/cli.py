"""CLI for idempotently importing the configured private Discord CSV."""

from __future__ import annotations

import argparse
import asyncio
import os

from sqlalchemy import func, select

from app.config import ConfigurationError, get_settings
from app.db.migrations import upgrade_database
from app.db.session import create_database_engine, create_session_factory
from app.db.tables import ChannelConfig, MessageHead, MessageSnapshot
from app.ingestion.csv_source import CsvMessageSource
from app.ingestion.normalizer import MessageNormalizer
from app.worker.lease import ChannelLeaseManager
from app.worker.scanner import ChannelScanner


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import a private Discord CSV into durable canonical storage."
    )
    parser.add_argument("--database-url", help="Override DATABASE_URL for this run")
    parser.add_argument("--page-size", type=int, default=100)
    return parser.parse_args()


def _ensure_channel_configs(source: CsvMessageSource, sessions) -> list[int]:
    config_ids: list[int] = []
    with sessions.begin() as session:
        for channel_ref in source.channel_refs:
            guild_id, channel_id = channel_ref.split(":", 1)
            config = session.scalar(
                select(ChannelConfig).where(
                    ChannelConfig.guild_id == guild_id,
                    ChannelConfig.channel_id == channel_id,
                )
            )
            if config is None:
                config = ChannelConfig(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    enabled=True,
                    source_type="csv",
                )
                session.add(config)
                session.flush()
            elif config.source_type != "csv":
                raise ConfigurationError(
                    f"Channel {guild_id}:{channel_id} already uses source {config.source_type}."
                )
            config_ids.append(config.id)
    return config_ids


async def _run_import(database_url: str, page_size: int) -> tuple[int, int, int]:
    settings = get_settings()
    (messages_path,) = settings.require_paths("private_messages_csv")
    source = CsvMessageSource(messages_path)
    engine = create_database_engine(database_url)
    upgrade_database(engine)
    sessions = create_session_factory(engine)
    scanner = ChannelScanner(
        sessions,
        MessageNormalizer(
            settings.require_identity_hash_salt(),
            support_role_ids=settings.support_role_ids,
            approved_bot_ids=settings.approved_bot_ids,
        ),
        ChannelLeaseManager(sessions),
        page_size=page_size,
    )
    config_ids = _ensure_channel_configs(source, sessions)
    imported = 0
    owner = f"phase1-cli-{os.getpid()}"
    for config_id in config_ids:
        result = await scanner.scan(config_id, source, owner=owner)
        if result.status != "SUCCESS":
            raise RuntimeError(
                f"Channel config {config_id} scan ended with {result.status}"
                + (f" ({result.error_code})" if result.error_code else "")
            )
        imported += result.snapshots_created

    with sessions() as session:
        snapshots = session.scalar(select(func.count()).select_from(MessageSnapshot)) or 0
        heads = session.scalar(select(func.count()).select_from(MessageHead)) or 0
    engine.dispose()
    return imported, snapshots, heads


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    if args.page_size <= 0:
        raise SystemExit("--page-size must be positive")
    database_url = args.database_url or settings.database_url
    try:
        imported, snapshots, heads = asyncio.run(_run_import(database_url, args.page_size))
    except (ConfigurationError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Phase 1 ingestion failed: {exc}") from exc

    print("Phase 1 ingestion completed.")
    print(f"New snapshots: {imported}")
    print(f"Total snapshots: {snapshots}")
    print(f"Current message heads: {heads}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
