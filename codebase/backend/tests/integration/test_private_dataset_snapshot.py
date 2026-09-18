from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.eval.dataset_validator import validate_datasets


def _private_path(name: str) -> Path:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    path = Path(value)
    if not path.is_file():
        pytest.skip(f"{name} does not point to a readable file")
    return path


@pytest.mark.private_data
def test_current_private_dataset_snapshot() -> None:
    messages = _private_path("PRIVATE_MESSAGES_CSV")
    labels = _private_path("PRIVATE_LABELS_CSV")
    train_value = os.getenv("PRIVATE_TRAIN_CSV")
    golden_value = os.getenv("PRIVATE_GOLDEN_CSV")

    report = validate_datasets(
        messages,
        labels,
        train_path=Path(train_value) if train_value else None,
        golden_path=Path(golden_value) if golden_value else None,
    )

    assert report.is_valid
    assert report.message_rows == 1092
    assert report.labeled_rows == 311
    assert report.label_distribution == {"0": 273, "1": 30, "2": 8}
    assert report.invalid_labels == 0
    assert report.missing_label_reasons == 137
    assert report.duplicate_msg_id_groups == 1
    assert report.duplicate_offline_key_groups == 1
    assert report.exact_content_duplicate_groups == 5
    assert report.normalized_content_duplicate_groups == 6

    if train_value and golden_value:
        assert report.split is not None
        assert report.split.train_urgent_rows == 0
        assert report.split.golden_master_urgent_rows == 8
        assert report.split.golden_contains_all_master_urgent
