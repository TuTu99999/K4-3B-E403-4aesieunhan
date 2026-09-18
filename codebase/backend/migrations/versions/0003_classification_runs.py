"""Add versioned classifier execution/cache records.

Revision ID: 0003_classification_runs
"""

from __future__ import annotations

from sqlalchemy import Connection

from app.db.base import Base
from app.db.tables import ClassificationRun

revision = "0003_classification_runs"
down_revision = "0002_candidates"


def upgrade(connection: Connection) -> None:
    Base.metadata.create_all(connection, tables=[ClassificationRun.__table__])


def downgrade(connection: Connection) -> None:
    Base.metadata.drop_all(connection, tables=[ClassificationRun.__table__])
