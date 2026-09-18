"""Idempotent page-by-page message ingestion scanner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, sessionmaker

from app.db.repositories import MessageStore, ensure_cursor
from app.db.tables import ChannelConfig, WorkerCursor
from app.ingestion.base import (
    MessageSource,
    SourceError,
    SourceMessage,
    SourcePermissionDenied,
    SourceProtocolError,
    SourceTemporarilyUnavailable,
)
from app.ingestion.normalizer import MessageNormalizer
from app.worker.lease import ChannelLeaseManager


@dataclass(frozen=True, slots=True)
class ScanResult:
    channel_config_id: int
    status: str
    pages: int = 0
    records_seen: int = 0
    snapshots_created: int = 0
    error_code: str | None = None


class LeaseLostError(RuntimeError):
    pass


class ChannelScanner:
    """Persist source pages before advancing their opaque cursor."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        normalizer: MessageNormalizer,
        lease_manager: ChannelLeaseManager,
        *,
        page_size: int = 100,
        lease_ttl: timedelta = timedelta(minutes=5),
        permission_pause: timedelta = timedelta(minutes=15),
        store: MessageStore | None = None,
    ) -> None:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self._session_factory = session_factory
        self._normalizer = normalizer
        self._lease_manager = lease_manager
        self._page_size = page_size
        self._lease_ttl = lease_ttl
        self._permission_pause = permission_pause
        self._store = store or MessageStore()

    async def scan(
        self,
        channel_config_id: int,
        source: MessageSource,
        *,
        owner: str,
    ) -> ScanResult:
        config = self._load_config(channel_config_id)
        if not config.enabled:
            return ScanResult(channel_config_id, "DISABLED")
        paused_error = self._active_pause(channel_config_id)
        if paused_error is not None:
            return ScanResult(
                channel_config_id,
                "PAUSED_PERMISSION",
                error_code=paused_error,
            )
        if config.source_type != source.source_kind:
            raise ValueError(
                f"source mismatch: channel expects {config.source_type}, got {source.source_kind}"
            )
        if not self._lease_manager.acquire(channel_config_id, owner, self._lease_ttl):
            return ScanResult(channel_config_id, "LEASE_BUSY")

        pages = records_seen = snapshots_created = 0
        try:
            cursor = self._load_cursor(channel_config_id)
            channel_ref = self._channel_ref(config)
            while True:
                page = await source.fetch_after(channel_ref, cursor, self._page_size)
                if page.has_more and not page.records:
                    raise SourceProtocolError("source returned an empty non-final page")
                if page.records and page.next_cursor == cursor:
                    raise SourceTemporarilyUnavailable("source cursor did not advance")

                now = datetime.now(timezone.utc)
                with self._session_factory.begin() as session:
                    for record in page.records:
                        normalized = self._normalizer.normalize(record)
                        _, created = self._store.persist(session, channel_config_id, normalized)
                        snapshots_created += int(created)
                    durable_cursor = ensure_cursor(session, channel_config_id)
                    durable_cursor.last_message_id = page.next_cursor
                    durable_cursor.last_scanned_at = now
                    durable_cursor.last_error_code = None
                    durable_cursor.last_error_at = None
                    durable_cursor.disabled_until = None
                    durable_cursor.version += 1

                pages += 1
                records_seen += len(page.records)
                cursor = page.next_cursor
                if not self._lease_manager.renew(
                    channel_config_id, owner, self._lease_ttl
                ):
                    raise LeaseLostError("channel lease expired while scanning")
                if not page.has_more:
                    return ScanResult(
                        channel_config_id,
                        "SUCCESS",
                        pages=pages,
                        records_seen=records_seen,
                        snapshots_created=snapshots_created,
                    )
        except SourcePermissionDenied as exc:
            self._record_source_failure(
                channel_config_id,
                exc.code,
                disabled_until=datetime.now(timezone.utc) + self._permission_pause,
            )
            return ScanResult(
                channel_config_id,
                "PAUSED_PERMISSION",
                pages,
                records_seen,
                snapshots_created,
                exc.code,
            )
        except SourceError as exc:
            self._record_source_failure(channel_config_id, exc.code)
            return ScanResult(
                channel_config_id,
                "SOURCE_ERROR",
                pages,
                records_seen,
                snapshots_created,
                exc.code,
            )
        finally:
            self._lease_manager.release(channel_config_id, owner)

    def ingest_event(self, channel_config_id: int, record: SourceMessage) -> bool:
        """Persist a gateway/reconciliation edit or delete without moving the scan cursor."""

        config = self._load_config(channel_config_id)
        if config.source_type != record.source:
            raise ValueError("event source does not match channel configuration")
        if config.guild_id != record.guild_id or config.channel_id != record.channel_id:
            raise ValueError("event is outside the configured channel")
        with self._session_factory.begin() as session:
            _, created = self._store.persist(
                session,
                channel_config_id,
                self._normalizer.normalize(record),
            )
            return created

    def _load_config(self, channel_config_id: int) -> ChannelConfig:
        with self._session_factory() as session:
            config = session.get(ChannelConfig, channel_config_id)
            if config is None:
                raise LookupError(f"channel config {channel_config_id} does not exist")
            session.expunge(config)
            return config

    def _load_cursor(self, channel_config_id: int) -> str | None:
        with self._session_factory.begin() as session:
            return ensure_cursor(session, channel_config_id).last_message_id

    def _active_pause(self, channel_config_id: int) -> str | None:
        with self._session_factory() as session:
            cursor = session.get(WorkerCursor, channel_config_id)
            if (
                cursor is not None
                and cursor.disabled_until is not None
                and cursor.disabled_until > datetime.now(timezone.utc)
            ):
                return cursor.last_error_code or "PERMISSION_DENIED"
            return None

    @staticmethod
    def _channel_ref(config: ChannelConfig) -> str:
        if config.source_type == "csv":
            return f"{config.guild_id}:{config.channel_id}"
        return config.channel_id

    def _record_source_failure(
        self,
        channel_config_id: int,
        error_code: str,
        *,
        disabled_until: datetime | None = None,
    ) -> None:
        with self._session_factory.begin() as session:
            cursor = ensure_cursor(session, channel_config_id)
            cursor.last_error_code = error_code
            cursor.last_error_at = datetime.now(timezone.utc)
            cursor.disabled_until = disabled_until
            cursor.version += 1
