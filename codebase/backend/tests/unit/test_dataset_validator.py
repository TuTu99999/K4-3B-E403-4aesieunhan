from pathlib import Path

from app.eval.dataset_validator import build_split_manifest, validate_datasets
from tests.helpers import labeled_values, message_values, write_labels, write_messages


def test_reports_warnings_and_composite_key_collision(tmp_path: Path) -> None:
    messages = write_messages(
        tmp_path / "messages.csv",
        [message_values(msg_id="M90001"), message_values(msg_id="M90002")],
    )
    duplicate = labeled_values(label_reason="")
    labels = write_labels(tmp_path / "labels.csv", [duplicate, duplicate])

    report = validate_datasets(messages, labels)

    assert report.is_valid
    assert report.missing_label_reasons == 2
    assert report.duplicate_msg_id_groups == 1
    assert report.duplicate_offline_key_groups == 1
    assert report.exact_content_duplicate_groups == 1
    assert report.normalized_content_duplicate_groups == 1
    assert any("blank label_reason" in warning for warning in report.warnings)


def test_split_requires_all_master_urgent_in_golden(tmp_path: Path) -> None:
    messages = write_messages(tmp_path / "messages.csv", [message_values()])
    master_rows = [
        labeled_values(msg_id="M90001", label="0"),
        labeled_values(msg_id="M90002", label="1"),
        labeled_values(msg_id="M90003", label="2"),
    ]
    labels = write_labels(tmp_path / "labels.csv", master_rows)
    train = write_labels(tmp_path / "train.csv", master_rows[:2])
    golden = write_labels(tmp_path / "golden.csv", [master_rows[2]])

    report = validate_datasets(
        messages,
        labels,
        train_path=train,
        golden_path=golden,
    )

    assert report.is_valid
    assert report.split is not None
    assert report.split.golden_contains_all_master_urgent
    assert report.split.train_urgent_rows == 0


def test_split_manifest_contains_hashes_not_content(tmp_path: Path) -> None:
    secret_content = "Nội dung riêng tư không được ghi vào manifest"
    train = write_labels(
        tmp_path / "train.csv",
        [labeled_values(content=secret_content, label="0")],
    )
    golden = write_labels(
        tmp_path / "golden.csv",
        [labeled_values(msg_id="M90002", content="Câu thử giả", label="2")],
    )

    manifest = build_split_manifest(train, golden)
    rendered = str(manifest)

    assert secret_content not in rendered
    assert len(manifest["train"]["file_sha256"]) == 64
    assert len(manifest["train"]["row_identity_hashes"][0]) == 64
