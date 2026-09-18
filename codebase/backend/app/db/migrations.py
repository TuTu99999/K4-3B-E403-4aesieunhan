"""Small migration runner used by tests and the local prototype."""

from __future__ import annotations

import importlib

from sqlalchemy import Engine

MIGRATIONS = (
    "migrations.versions.0001_initial",
    "migrations.versions.0002_candidates",
    "migrations.versions.0003_classification_runs",
)


def upgrade_database(engine: Engine) -> None:
    with engine.begin() as connection:
        for module_name in MIGRATIONS:
            importlib.import_module(module_name).upgrade(connection)


def downgrade_database(engine: Engine) -> None:
    with engine.begin() as connection:
        for module_name in reversed(MIGRATIONS):
            importlib.import_module(module_name).downgrade(connection)
