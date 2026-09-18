from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from app.domain.candidate import CandidateMessage
from app.domain.models import LABELED_COLUMNS, MESSAGE_COLUMNS


def message_values(**overrides: str) -> dict[str, str]:
    values = {
        "msg_id": "M90001",
        "guild": "TEST-GUILD",
        "channel": "channel_test",
        "author": "D0001",
        "is_bot": "False",
        "msg_type": "message",
        "created_at_vn": "2026-09-18 09:00",
        "reply_to": "",
        "mentions_bot": "False",
        "n_attachments": "0",
        "n_chars": "18",
        "content": "Cần hỗ trợ giúp em",
    }
    values.update(overrides)
    return values


def labeled_values(**overrides: str) -> dict[str, str]:
    values = message_values()
    values.update({"label": "1", "label_reason": "Câu hỏi hỗ trợ chung"})
    values.update(overrides)
    return values


def write_csv(
    path: Path,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, str]],
    *,
    delimiter: str,
) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_messages(path: Path, rows: Iterable[Mapping[str, str]]) -> Path:
    return write_csv(path, MESSAGE_COLUMNS, rows, delimiter=",")


def write_labels(path: Path, rows: Iterable[Mapping[str, str]]) -> Path:
    return write_csv(path, LABELED_COLUMNS, rows, delimiter=";")


def candidate_message(**overrides: object) -> CandidateMessage:
    values: dict[str, object] = {
        "snapshot_id": 1,
        "message_key": "G1:C1:M00001",
        "content_version": "v1",
        "guild_id": "G1",
        "channel_id": "C1",
        "thread_id": None,
        "author_id_hash": "author-a",
        "author_role_type": "student",
        "is_bot": False,
        "is_webhook": False,
        "is_system": False,
        "message_type": "message",
        "reply_to_key": None,
        "content_redacted": "Em cần hỗ trợ",
        "content_hash": "content-a",
        "attachment_count": 0,
        "created_at_utc": datetime(2026, 9, 18, 2, tzinfo=timezone.utc),
        "edited_at_utc": None,
        "deleted_at_utc": None,
        "effective_at_utc": datetime(2026, 9, 18, 2, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return CandidateMessage(**values)  # type: ignore[arg-type]
