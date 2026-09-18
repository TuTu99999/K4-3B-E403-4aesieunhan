from pathlib import Path

from app.domain.enums import ActionLabel
from app.ingestion.csv_loader import load_labeled_rows


def test_public_fixture_is_synthetic_complete_and_consistent() -> None:
    repository_root = Path(__file__).resolve().parents[4]
    fixture = repository_root / "eval" / "fixtures" / "public_sample.csv"

    rows = load_labeled_rows(fixture).rows

    assert len(rows) == 12
    assert all(row.msg_id.startswith("M9") for row in rows)
    assert all(row.n_chars == len(row.content) for row in rows)
    assert sum(row.label == ActionLabel.IGNORE for row in rows) == 6
    assert sum(row.label == ActionLabel.NORMAL for row in rows) == 3
    assert sum(row.label == ActionLabel.URGENT for row in rows) == 3
