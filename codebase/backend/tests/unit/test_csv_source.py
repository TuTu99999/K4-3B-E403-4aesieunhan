from __future__ import annotations

import asyncio

from app.ingestion.csv_source import CsvMessageSource
from tests.helpers import message_values, write_messages


def test_csv_source_uses_timezone_and_stable_tie_breaker(tmp_path) -> None:
    csv_path = write_messages(
        tmp_path / "messages.csv",
        [
            message_values(msg_id="M00002", created_at_vn="2026-09-18 09:00"),
            message_values(
                msg_id="M00001",
                created_at_vn="2026-09-18 09:00",
                msg_type="reply",
                reply_to="M00002",
            ),
        ],
    )
    source = CsvMessageSource(csv_path)

    first = asyncio.run(source.fetch_after("TEST-GUILD:channel_test", None, 1))
    second = asyncio.run(
        source.fetch_after("TEST-GUILD:channel_test", first.next_cursor, 1)
    )

    assert first.records[0].message_id == "M00001"
    assert second.records[0].message_id == "M00002"
    assert first.records[0].created_at_utc.isoformat() == "2026-09-18T02:00:00+00:00"
    assert first.next_cursor != second.next_cursor


def test_csv_source_indexes_direct_replies(tmp_path) -> None:
    csv_path = write_messages(
        tmp_path / "messages.csv",
        [
            message_values(msg_id="M00001"),
            message_values(msg_id="M00002", msg_type="reply", reply_to="M00001"),
        ],
    )
    source = CsvMessageSource(csv_path)

    replies = asyncio.run(source.fetch_direct_replies("TEST-GUILD:channel_test:M00001"))

    assert [reply.message_id for reply in replies] == ["M00002"]


def test_csv_cursor_does_not_drop_repeated_key_at_page_boundary(tmp_path) -> None:
    csv_path = write_messages(
        tmp_path / "messages.csv",
        [
            message_values(msg_id="M00001", content="Phiên bản A"),
            message_values(msg_id="M00001", content="Phiên bản B"),
        ],
    )
    source = CsvMessageSource(csv_path)

    first = asyncio.run(source.fetch_after("TEST-GUILD:channel_test", None, 1))
    second = asyncio.run(
        source.fetch_after("TEST-GUILD:channel_test", first.next_cursor, 1)
    )

    assert first.records[0].content == "Phiên bản A"
    assert second.records[0].content == "Phiên bản B"
    assert first.next_cursor != second.next_cursor


def test_same_anonymized_id_in_different_guilds_does_not_collide(tmp_path) -> None:
    csv_path = write_messages(
        tmp_path / "messages.csv",
        [
            message_values(msg_id="M00001", guild="GUILD-A"),
            message_values(msg_id="M00001", guild="GUILD-B"),
        ],
    )
    source = CsvMessageSource(csv_path)

    first = asyncio.run(source.fetch_after("GUILD-A:channel_test", None, 10))
    second = asyncio.run(source.fetch_after("GUILD-B:channel_test", None, 10))

    assert first.records[0].message_key == "GUILD-A:channel_test:M00001"
    assert second.records[0].message_key == "GUILD-B:channel_test:M00001"
