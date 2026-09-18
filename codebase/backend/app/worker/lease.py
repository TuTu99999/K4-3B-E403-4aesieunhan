"""Atomic per-channel worker leases."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.repositories import ensure_cursor
from app.db.tables import WorkerCursor


class ChannelLeaseManager:
    """Coordinate scanners without relying on in-process locks."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def acquire(
        self,
        channel_config_id: int,
        owner: str,
        ttl: timedelta,
        *,
        now: datetime | None = None,
    ) -> bool:
        current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expires_at = current_time + ttl
        self._ensure_row(channel_config_id)
        with self._session_factory.begin() as session:
            result = session.execute(
                update(WorkerCursor)
                .where(
                    WorkerCursor.channel_config_id == channel_config_id,
                    or_(
                        WorkerCursor.lease_owner.is_(None),
                        WorkerCursor.lease_expires_at.is_(None),
                        WorkerCursor.lease_expires_at <= current_time,
                        WorkerCursor.lease_owner == owner,
                    ),
                )
                .values(
                    lease_owner=owner,
                    lease_expires_at=expires_at,
                    version=WorkerCursor.version + 1,
                )
            )
            return result.rowcount == 1

    def renew(
        self,
        channel_config_id: int,
        owner: str,
        ttl: timedelta,
        *,
        now: datetime | None = None,
    ) -> bool:
        current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._session_factory.begin() as session:
            result = session.execute(
                update(WorkerCursor)
                .where(
                    WorkerCursor.channel_config_id == channel_config_id,
                    WorkerCursor.lease_owner == owner,
                    WorkerCursor.lease_expires_at > current_time,
                )
                .values(
                    lease_expires_at=current_time + ttl,
                    version=WorkerCursor.version + 1,
                )
            )
            return result.rowcount == 1

    def release(self, channel_config_id: int, owner: str) -> bool:
        with self._session_factory.begin() as session:
            result = session.execute(
                update(WorkerCursor)
                .where(
                    WorkerCursor.channel_config_id == channel_config_id,
                    WorkerCursor.lease_owner == owner,
                )
                .values(
                    lease_owner=None,
                    lease_expires_at=None,
                    version=WorkerCursor.version + 1,
                )
            )
            return result.rowcount == 1

    def _ensure_row(self, channel_config_id: int) -> None:
        try:
            with self._session_factory.begin() as session:
                ensure_cursor(session, channel_config_id)
        except IntegrityError:
            # Another worker won the insert race. The following atomic UPDATE decides the lease.
            pass
