"""Add rule-engine candidates and privacy-safe decision audits.

Revision ID: 0002_candidates
"""

from __future__ import annotations

from sqlalchemy import Connection, update

from app.db.base import Base
from app.db.tables import CandidateRecord, MessageSnapshot, RuleAudit

revision = "0002_candidates"
down_revision = "0001_initial"


def upgrade(connection: Connection) -> None:
    Base.metadata.create_all(
        connection,
        tables=[CandidateRecord.__table__, RuleAudit.__table__],
    )
    # Phase 1 CSV imports predated role resolution. Offline non-bot records are students;
    # live support roles are resolved before persistence by MessageNormalizer.
    connection.execute(
        update(MessageSnapshot)
        .where(
            MessageSnapshot.source_type == "csv",
            MessageSnapshot.is_bot.is_(False),
            MessageSnapshot.author_role_type.in_(("unknown", "member_with_roles")),
        )
        .values(author_role_type="student")
    )


def downgrade(connection: Connection) -> None:
    Base.metadata.drop_all(
        connection,
        tables=[RuleAudit.__table__, CandidateRecord.__table__],
    )
