from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.ingestion.base import SourceAttachment, SourceMessage
from app.ingestion.normalizer import MessageNormalizer, redact_content


def source_message(**overrides: object) -> SourceMessage:
    values: dict[str, object] = {
        "source": "csv",
        "guild_id": "G1",
        "channel_id": "C1",
        "message_id": "M00001",
        "author_id": "D0001",
        "message_type": "message",
        "content": "Em không vào được lớp",
        "created_at_utc": datetime(2026, 9, 18, 2, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SourceMessage.model_validate(values)


def test_redacts_pii_and_credentials_before_persistence() -> None:
    raw = (
        "mail me@example.com, phone 0912 345 678, "
        "Bearer abcdefghijklmnop and api_key=supersecretvalue"
    )
    redacted = redact_content(raw)

    assert "me@example.com" not in redacted
    assert "0912 345 678" not in redacted
    assert "abcdefghijklmnop" not in redacted
    assert "supersecretvalue" not in redacted
    assert redacted.count("REDACTED") == 4


def test_normalization_is_stable_and_hashes_author_with_salt() -> None:
    source = source_message()
    first = MessageNormalizer("a-private-test-salt").normalize(source)
    second = MessageNormalizer("a-private-test-salt").normalize(source)
    other_salt = MessageNormalizer("another-private-salt").normalize(source)

    assert first.content_version == second.content_version
    assert first.author_id_hash == second.author_id_hash
    assert first.author_id_hash != other_salt.author_id_hash
    assert first.author_id not in repr(first)


def test_edit_and_delete_create_new_content_versions() -> None:
    created = source_message()
    edited = source_message(
        content="Em vẫn không vào được lớp",
        edited_at_utc=created.created_at_utc + timedelta(minutes=2),
    )
    deleted = source_message(
        content="Em vẫn không vào được lớp",
        edited_at_utc=edited.edited_at_utc,
        deleted_at_utc=created.created_at_utc + timedelta(minutes=3),
    )
    normalizer = MessageNormalizer("a-private-test-salt")

    versions = {
        normalizer.normalize(created).content_version,
        normalizer.normalize(edited).content_version,
        normalizer.normalize(deleted).content_version,
    }

    assert len(versions) == 3
    assert normalizer.normalize(deleted).effective_at_utc == deleted.deleted_at_utc


def test_attachment_metadata_affects_version_without_loading_bytes() -> None:
    normalizer = MessageNormalizer("a-private-test-salt")
    without_file = normalizer.normalize(source_message())
    with_file = normalizer.normalize(
        source_message(
            attachments=(
                SourceAttachment(
                    attachment_id="A1",
                    filename="error.png",
                    media_type="image/png",
                    size_bytes=120,
                ),
            )
        )
    )

    assert without_file.content_version != with_file.content_version
    assert with_file.attachment_metadata[0].filename == "error.png"


def test_roles_are_resolved_from_allowlists() -> None:
    normalizer = MessageNormalizer(
        "a-private-test-salt",
        support_role_ids=frozenset({"ta-role"}),
        approved_bot_ids=frozenset({"approved-bot"}),
    )

    student = normalizer.normalize(source_message(author_roles=frozenset({"learner"})))
    support = normalizer.normalize(source_message(author_roles=frozenset({"ta-role"})))
    bot = normalizer.normalize(source_message(author_id="random-bot", is_bot=True))
    approved = normalizer.normalize(
        source_message(author_id="approved-bot", is_bot=True)
    )

    assert student.author_role_type == "student"
    assert support.author_role_type == "support"
    assert bot.author_role_type == "bot"
    assert approved.author_role_type == "approved_bot"
