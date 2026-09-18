from pathlib import Path

import pytest

from app.domain.enums import ActionLabel
from app.ingestion.csv_loader import (
    CsvRowValidationError,
    HeaderMismatchError,
    load_labeled_rows,
    load_message_rows,
)
from tests.helpers import labeled_values, message_values, write_labels, write_messages


def test_parses_utf8_emoji_and_quoted_semicolon(tmp_path: Path) -> None:
    content = "Em cần hỗ trợ; gấp 😅"
    path = write_labels(
        tmp_path / "labels.csv",
        [labeled_values(content=content, n_chars=str(len(content)))],
    )

    result = load_labeled_rows(path)

    assert result.delimiter == ";"
    assert result.rows[0].content == content
    assert result.rows[0].label == ActionLabel.NORMAL


def test_detects_comma_delimited_raw_messages(tmp_path: Path) -> None:
    path = write_messages(tmp_path / "messages.csv", [message_values()])

    result = load_message_rows(path)

    assert result.delimiter == ","
    assert result.rows[0].offline_key == "TEST-GUILD:channel_test:M90001"


@pytest.mark.parametrize("label", ["", "3", "9", "urgent"])
def test_rejects_blank_or_invalid_dataset_label(tmp_path: Path, label: str) -> None:
    path = write_labels(tmp_path / "labels.csv", [labeled_values(label=label)])

    with pytest.raises(CsvRowValidationError, match="label"):
        load_labeled_rows(path)


def test_accepts_blank_label_reason(tmp_path: Path) -> None:
    path = write_labels(tmp_path / "labels.csv", [labeled_values(label_reason="")])

    result = load_labeled_rows(path)

    assert result.rows[0].label_reason is None


def test_rejects_negative_counts_and_bad_reply_format(tmp_path: Path) -> None:
    path = write_labels(
        tmp_path / "labels.csv",
        [labeled_values(n_attachments="-1", reply_to="not-a-message-id")],
    )

    with pytest.raises(CsvRowValidationError) as error:
        load_labeled_rows(path)

    fields = {issue.field for issue in error.value.issues}
    assert {"n_attachments", "reply_to"} <= fields


def test_rejects_changed_header(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    path.write_text("msg_id;unexpected\nM90001;value\n", encoding="utf-8")

    with pytest.raises(HeaderMismatchError):
        load_labeled_rows(path)
