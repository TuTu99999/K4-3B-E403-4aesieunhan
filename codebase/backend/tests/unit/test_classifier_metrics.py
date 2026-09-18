import pytest

from app.eval.metrics import compute_classification_metrics, quality_bar


def test_metrics_publish_denominators_and_review_as_a_distinct_class() -> None:
    metrics = compute_classification_metrics(
        [0, 1, 2, 2],
        [0, 1, 3, 2],
        latencies_ms=[10, 20, 30, 100],
        total_tokens=80,
    )

    assert metrics["actionable_recall"] == {"value": 0.6667, "found": 2, "total": 3}
    assert metrics["urgent_recall"] == {"value": 0.5, "found": 1, "total": 2}
    assert metrics["review_rate"] == {"value": 0.25, "reviewed": 1, "total": 4}
    assert metrics["latency_ms"] == {"p50": 25, "p95": 100}
    assert metrics["macro_f1"] == 0.8889
    assert metrics["macro_f1_including_review"] == 0.6667
    assert not all(quality_bar(metrics).values())


def test_metrics_reject_empty_or_misaligned_predictions() -> None:
    with pytest.raises(ValueError, match="at least one"):
        compute_classification_metrics([], [])
    with pytest.raises(ValueError, match="equal length"):
        compute_classification_metrics([0], [])
