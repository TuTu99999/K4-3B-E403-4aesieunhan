"""Strict, privacy-safe CSV loaders for offline Discord fixtures."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.domain.models import (
    LABELED_COLUMNS,
    MESSAGE_COLUMNS,
    LabeledRow,
    MessageRow,
)

RowModel = TypeVar("RowModel", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class CsvIssue:
    row_number: int
    field: str
    message: str

    def __str__(self) -> str:
        return f"row {self.row_number}, field {self.field}: {self.message}"


@dataclass(frozen=True, slots=True)
class CsvLoadResult(Generic[RowModel]):
    rows: tuple[RowModel, ...]
    delimiter: str


class CsvDatasetError(ValueError):
    """Base error for invalid CSV datasets."""


class HeaderMismatchError(CsvDatasetError):
    def __init__(self, expected: tuple[str, ...], actual: tuple[str, ...]) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            "CSV header mismatch. "
            f"Expected {list(expected)}, received {list(actual)}. "
            "Update the canonical schema deliberately before accepting a changed export."
        )


class CsvRowValidationError(CsvDatasetError):
    def __init__(self, issues: list[CsvIssue]) -> None:
        self.issues = tuple(issues)
        preview = "; ".join(str(issue) for issue in issues[:8])
        suffix = "" if len(issues) <= 8 else f"; ... and {len(issues) - 8} more"
        super().__init__(f"CSV contains {len(issues)} invalid value(s): {preview}{suffix}")


def _read_header(path: Path, delimiter: str) -> tuple[str, ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter, strict=True)
        try:
            return tuple(next(reader))
        except StopIteration as exc:
            raise CsvDatasetError(f"CSV is empty: {path.name}") from exc
        except csv.Error as exc:
            raise CsvDatasetError(f"Cannot parse CSV header in {path.name}: {exc}") from exc


def _detect_delimiter(path: Path, expected_columns: tuple[str, ...]) -> str:
    """Match the canonical header using a real CSV reader, never line splitting."""

    observed: dict[str, tuple[str, ...]] = {}
    for delimiter in (";", ","):
        header = _read_header(path, delimiter)
        observed[delimiter] = header
        if header == expected_columns:
            return delimiter

    most_columns = max(observed.values(), key=len)
    raise HeaderMismatchError(expected_columns, most_columns)


def _issues_from_error(row_number: int, error: ValidationError) -> list[CsvIssue]:
    issues: list[CsvIssue] = []
    for detail in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in detail["loc"]) or "<row>"
        issues.append(
            CsvIssue(
                row_number=row_number,
                field=location,
                message=detail["msg"],
            )
        )
    return issues


def _load_rows(
    path: str | Path,
    *,
    model: type[RowModel],
    expected_columns: tuple[str, ...],
) -> CsvLoadResult[RowModel]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"CSV file does not exist: {source}")

    delimiter = _detect_delimiter(source, expected_columns)
    rows: list[RowModel] = []
    issues: list[CsvIssue] = []

    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter, strict=True)
        if tuple(reader.fieldnames or ()) != expected_columns:
            raise HeaderMismatchError(expected_columns, tuple(reader.fieldnames or ()))

        try:
            for row_number, raw_row in enumerate(reader, start=2):
                if None in raw_row:
                    issues.append(
                        CsvIssue(
                            row_number=row_number,
                            field="<row>",
                            message="row has more fields than the canonical header",
                        )
                    )
                    continue
                try:
                    rows.append(model.model_validate(raw_row))
                except ValidationError as exc:
                    issues.extend(_issues_from_error(row_number, exc))
        except csv.Error as exc:
            issues.append(
                CsvIssue(
                    row_number=reader.line_num,
                    field="<csv>",
                    message=str(exc),
                )
            )

    if issues:
        raise CsvRowValidationError(issues)
    return CsvLoadResult(rows=tuple(rows), delimiter=delimiter)


def load_message_rows(path: str | Path) -> CsvLoadResult[MessageRow]:
    return _load_rows(path, model=MessageRow, expected_columns=MESSAGE_COLUMNS)


def load_labeled_rows(path: str | Path) -> CsvLoadResult[LabeledRow]:
    return _load_rows(path, model=LabeledRow, expected_columns=LABELED_COLUMNS)
