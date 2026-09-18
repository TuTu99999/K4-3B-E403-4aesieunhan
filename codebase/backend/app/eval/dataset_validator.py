"""Validate private datasets without copying their content into the repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.config import ConfigurationError, Settings, get_settings
from app.domain.enums import ActionLabel
from app.domain.models import LabeledRow, MessageRow
from app.ingestion.csv_loader import CsvDatasetError, load_labeled_rows, load_message_rows


@dataclass(frozen=True, slots=True)
class SplitReport:
    train_rows: int
    golden_rows: int
    train_label_distribution: dict[str, int]
    golden_label_distribution: dict[str, int]
    train_urgent_rows: int
    master_urgent_rows: int
    golden_master_urgent_rows: int
    golden_contains_all_master_urgent: bool
    shared_offline_key_groups: int


@dataclass(frozen=True, slots=True)
class DatasetReport:
    message_rows: int
    labeled_rows: int
    label_distribution: dict[str, int]
    invalid_labels: int
    missing_label_reasons: int
    duplicate_msg_id_groups: int
    duplicate_offline_key_groups: int
    exact_content_duplicate_groups: int
    normalized_content_duplicate_groups: int
    reply_targets_outside_message_pack: int
    message_csv_delimiter: str
    labeled_csv_delimiter: str
    split: SplitReport | None
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_content(value: str) -> str:
    """Normalize content for duplicate analysis without changing stored content."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _group_count(values: Sequence[str]) -> int:
    return sum(1 for count in Counter(values).values() if count > 1)


def _label_distribution(rows: Sequence[LabeledRow]) -> dict[str, int]:
    counts = Counter(int(row.label) for row in rows)
    return {str(label): counts.get(label, 0) for label in (0, 1, 2)}


def _build_split_report(
    master: Sequence[LabeledRow],
    train: Sequence[LabeledRow],
    golden: Sequence[LabeledRow],
) -> SplitReport:
    master_urgent_keys = {
        row.offline_key for row in master if row.label == ActionLabel.URGENT
    }
    golden_urgent_keys = {
        row.offline_key for row in golden if row.label == ActionLabel.URGENT
    }
    train_keys = {row.offline_key for row in train}
    golden_keys = {row.offline_key for row in golden}

    return SplitReport(
        train_rows=len(train),
        golden_rows=len(golden),
        train_label_distribution=_label_distribution(train),
        golden_label_distribution=_label_distribution(golden),
        train_urgent_rows=sum(row.label == ActionLabel.URGENT for row in train),
        master_urgent_rows=len(master_urgent_keys),
        golden_master_urgent_rows=len(master_urgent_keys & golden_urgent_keys),
        golden_contains_all_master_urgent=master_urgent_keys <= golden_urgent_keys,
        shared_offline_key_groups=len(train_keys & golden_keys),
    )


def validate_datasets(
    messages_path: str | Path,
    labels_path: str | Path,
    *,
    train_path: str | Path | None = None,
    golden_path: str | Path | None = None,
) -> DatasetReport:
    """Load datasets, enforce schema rules, and return aggregate-only diagnostics."""

    message_result = load_message_rows(messages_path)
    label_result = load_labeled_rows(labels_path)
    messages = message_result.rows
    labels = label_result.rows

    msg_ids = [row.msg_id for row in labels]
    offline_keys = [row.offline_key for row in labels]
    content = [row.content for row in labels]
    message_pack_ids = {row.msg_id for row in messages}

    missing_reasons = sum(row.label_reason is None for row in labels)
    duplicate_ids = _group_count(msg_ids)
    duplicate_keys = _group_count(offline_keys)
    duplicate_content = _group_count(content)
    normalized_duplicate_content = _group_count(
        [normalize_content(value) for value in content]
    )
    outside_replies = sum(
        row.reply_to is not None and row.reply_to not in message_pack_ids for row in messages
    )

    warnings: list[str] = []
    if missing_reasons:
        warnings.append(f"{missing_reasons} labeled row(s) have a blank label_reason")
    if duplicate_ids:
        warnings.append(f"{duplicate_ids} duplicate msg_id group(s) detected")
    if duplicate_keys:
        warnings.append(f"{duplicate_keys} duplicate offline-key group(s) detected")
    if duplicate_content:
        warnings.append(f"{duplicate_content} exact-content duplicate group(s) detected")
    if normalized_duplicate_content != duplicate_content:
        warnings.append(
            f"{normalized_duplicate_content} normalized-content duplicate group(s) detected"
        )
    if outside_replies:
        warnings.append(
            f"{outside_replies} reply row(s) target a message outside the raw message pack"
        )

    split_report: SplitReport | None = None
    errors: list[str] = []
    if (train_path is None) != (golden_path is None):
        errors.append("train_path and golden_path must be provided together")
    elif train_path is not None and golden_path is not None:
        train = load_labeled_rows(train_path).rows
        golden = load_labeled_rows(golden_path).rows
        split_report = _build_split_report(labels, train, golden)
        if split_report.train_urgent_rows:
            errors.append("train dataset must not contain URGENT rows")
        if not split_report.golden_contains_all_master_urgent:
            errors.append("golden dataset does not contain every URGENT row from the master labels")

    return DatasetReport(
        message_rows=len(messages),
        labeled_rows=len(labels),
        label_distribution=_label_distribution(labels),
        invalid_labels=0,
        missing_label_reasons=missing_reasons,
        duplicate_msg_id_groups=duplicate_ids,
        duplicate_offline_key_groups=duplicate_keys,
        exact_content_duplicate_groups=duplicate_content,
        normalized_content_duplicate_groups=normalized_duplicate_content,
        reply_targets_outside_message_pack=outside_replies,
        message_csv_delimiter=message_result.delimiter,
        labeled_csv_delimiter=label_result.delimiter,
        split=split_report,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_identity_hash(row: LabeledRow) -> str:
    content_hash = hashlib.sha256(normalize_content(row.content).encode("utf-8")).hexdigest()
    identity = "|".join(
        (
            row.offline_key,
            row.author,
            row.created_at_vn.isoformat(timespec="minutes"),
            content_hash,
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def build_split_manifest(
    train_path: str | Path,
    golden_path: str | Path,
) -> dict[str, Any]:
    """Build a private manifest containing hashes, never raw message content."""

    train_source = Path(train_path).expanduser().resolve()
    golden_source = Path(golden_path).expanduser().resolve()
    train = load_labeled_rows(train_source).rows
    golden = load_labeled_rows(golden_source).rows

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "train": {
            "rows": len(train),
            "label_distribution": _label_distribution(train),
            "file_sha256": _file_sha256(train_source),
            "row_identity_hashes": sorted(_row_identity_hash(row) for row in train),
        },
        "golden": {
            "rows": len(golden),
            "label_distribution": _label_distribution(golden),
            "file_sha256": _file_sha256(golden_source),
            "row_identity_hashes": sorted(_row_identity_hash(row) for row in golden),
        },
    }


def _write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    temporary.replace(destination)
    return destination


def _resolve_paths(
    args: argparse.Namespace, settings: Settings
) -> tuple[Path, Path, Path | None, Path | None]:
    if args.messages is not None:
        messages = args.messages.expanduser().resolve()
    else:
        (messages,) = settings.require_paths("private_messages_csv")

    if args.labels is not None:
        labels = args.labels.expanduser().resolve()
    else:
        (labels,) = settings.require_paths("private_labels_csv")

    train = args.train or settings.private_train_csv
    golden = args.golden or settings.private_golden_csv
    train = train.expanduser().resolve() if train is not None else None
    golden = golden.expanduser().resolve() if golden is not None else None
    return messages, labels, train, golden


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate private Discord CSV datasets without printing their content."
    )
    parser.add_argument("--messages", type=Path, help="Override PRIVATE_MESSAGES_CSV")
    parser.add_argument("--labels", type=Path, help="Override PRIVATE_LABELS_CSV")
    parser.add_argument("--train", type=Path, help="Override PRIVATE_TRAIN_CSV")
    parser.add_argument("--golden", type=Path, help="Override PRIVATE_GOLDEN_CSV")
    parser.add_argument("--json-output", type=Path, help="Write aggregate report JSON")
    parser.add_argument(
        "--manifest-output",
        type=Path,
        help="Write a private split manifest containing only hashes and counts",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def _print_text(report: DatasetReport) -> None:
    status = "PASS" if report.is_valid else "FAIL"
    print(f"Dataset validation: {status}")
    print(f"Messages: {report.message_rows}")
    print(f"Labeled: {report.labeled_rows}")
    print("Labels: " + ", ".join(f"{k}={v}" for k, v in report.label_distribution.items()))
    print(
        "Quality: "
        f"missing_reasons={report.missing_label_reasons}, "
        f"duplicate_msg_id_groups={report.duplicate_msg_id_groups}, "
        f"duplicate_offline_key_groups={report.duplicate_offline_key_groups}, "
        f"exact_content_duplicate_groups={report.exact_content_duplicate_groups}, "
        f"normalized_content_duplicate_groups={report.normalized_content_duplicate_groups}"
    )
    if report.split is not None:
        print(
            "Split: "
            f"train={report.split.train_rows}, golden={report.split.golden_rows}, "
            f"urgent_in_golden={report.split.golden_master_urgent_rows}/"
            f"{report.split.master_urgent_rows}"
        )
    for warning in report.warnings:
        print(f"WARNING: {warning}")
    for error in report.errors:
        print(f"ERROR: {error}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        messages, labels, train, golden = _resolve_paths(args, get_settings())
        report = validate_datasets(
            messages,
            labels,
            train_path=train,
            golden_path=golden,
        )
        if args.json_output is not None:
            _write_json(args.json_output, report.to_dict())
        if args.manifest_output is not None:
            if train is None or golden is None:
                raise ConfigurationError(
                    "PRIVATE_TRAIN_CSV and PRIVATE_GOLDEN_CSV are required for a split manifest"
                )
            _write_json(args.manifest_output, build_split_manifest(train, golden))

        if args.format == "json":
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            _print_text(report)
        return 0 if report.is_valid else 1
    except (ConfigurationError, CsvDatasetError, FileNotFoundError) as exc:
        print(f"Dataset validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
