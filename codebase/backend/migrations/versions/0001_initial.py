"""Create durable message-ingestion storage.

Revision ID: 0001_initial
"""

from __future__ import annotations

from sqlalchemy import Connection

from app.db.base import Base
from app.db.tables import ChannelConfig, MessageHead, MessageSnapshot, WorkerCursor

revision = "0001_initial"
down_revision = None


def upgrade(connection: Connection) -> None:
    Base.metadata.create_all(
        connection,
        tables=[
            ChannelConfig.__table__,
            WorkerCursor.__table__,
            MessageSnapshot.__table__,
            MessageHead.__table__,
        ],
    )


def downgrade(connection: Connection) -> None:
    Base.metadata.drop_all(
        connection,
        tables=[
            MessageHead.__table__,
            MessageSnapshot.__table__,
            WorkerCursor.__table__,
            ChannelConfig.__table__,
        ],
    )
