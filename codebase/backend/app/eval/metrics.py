"""Classification metrics with denominators suitable for imbalanced labels."""

from __future__ import annotations

from math import ceil
from statistics import median

LABEL_NAMES = {0: "IGNORE", 1: "NORMAL", 2: "URGENT", 3: "REVIEW"}


def _safe_div(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(ceil(percentile * len(ordered)) - 1, 0)
    return ordered[index]


def compute_classification_metrics(
    expected: list[int],
    predicted: list[int],
    *,
    latencies_ms: list[int] | None = None,
    total_tokens: int = 0,
) -> dict[str, object]:
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted must have equal length")
    if not expected:
        raise ValueError("metrics require at least one prediction")
    labels = (0, 1, 2, 3)
    confusion = {
        LABEL_NAMES[actual]: {
            LABEL_NAMES[prediction]: sum(
                1
                for truth, guess in zip(expected, predicted, strict=True)
                if truth == actual and guess == prediction
            )
            for prediction in labels
        }
        for actual in labels
    }
    per_class: dict[str, dict[str, float | int]] = {}
    f1_values: dict[int, float] = {}
    for label in labels:
        true_positive = sum(
            truth == label and guess == label
            for truth, guess in zip(expected, predicted, strict=True)
        )
        false_positive = sum(
            truth != label and guess == label
            for truth, guess in zip(expected, predicted, strict=True)
        )
        false_negative = sum(
            truth == label and guess != label
            for truth, guess in zip(expected, predicted, strict=True)
        )
        support = sum(truth == label for truth in expected)
        precision = _safe_div(true_positive, true_positive + false_positive)
        recall = _safe_div(true_positive, true_positive + false_negative)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        f1_values[label] = f1
        per_class[LABEL_NAMES[label]] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }

    actionable_total = sum(label in {1, 2} for label in expected)
    actionable_found = sum(
        truth in {1, 2} and guess in {1, 2}
        for truth, guess in zip(expected, predicted, strict=True)
    )
    notified = sum(guess in {1, 2} for guess in predicted)
    correct_notification_intent = sum(
        truth in {1, 2} and guess in {1, 2}
        for truth, guess in zip(expected, predicted, strict=True)
    )
    urgent_total = sum(label == 2 for label in expected)
    urgent_found = sum(
        truth == 2 and guess == 2
        for truth, guess in zip(expected, predicted, strict=True)
    )
    latencies = latencies_ms or []
    accuracy = _safe_div(
        sum(truth == guess for truth, guess in zip(expected, predicted, strict=True)),
        len(expected),
    )
    return {
        "total": len(expected),
        "accuracy": round(accuracy, 4),
        "confusion_matrix": confusion,
        "per_class": per_class,
        "macro_f1": round(sum(f1_values[label] for label in (0, 1, 2)) / 3, 4),
        "macro_f1_including_review": round(sum(f1_values.values()) / len(labels), 4),
        "actionable_recall": {
            "value": round(_safe_div(actionable_found, actionable_total), 4),
            "found": actionable_found,
            "total": actionable_total,
        },
        "urgent_recall": {
            "value": round(_safe_div(urgent_found, urgent_total), 4),
            "found": urgent_found,
            "total": urgent_total,
        },
        "notification_intent_precision": {
            "value": round(_safe_div(correct_notification_intent, notified), 4),
            "correct": correct_notification_intent,
            "total": notified,
        },
        "review_rate": {
            "value": round(_safe_div(predicted.count(3), len(predicted)), 4),
            "reviewed": predicted.count(3),
            "total": len(predicted),
        },
        "latency_ms": {
            "p50": round(median(latencies)) if latencies else 0,
            "p95": _percentile(latencies, 0.95),
        },
        "total_tokens": total_tokens,
    }


def quality_bar(metrics: dict[str, object]) -> dict[str, bool]:
    urgent = metrics["urgent_recall"]
    actionable = metrics["actionable_recall"]
    precision = metrics["notification_intent_precision"]
    assert isinstance(urgent, dict)
    assert isinstance(actionable, dict)
    assert isinstance(precision, dict)
    return {
        "urgent_recall_100_percent": urgent["value"] == 1.0,
        "actionable_recall_at_least_85_percent": actionable["value"] >= 0.85,
        "notification_precision_at_least_80_percent": precision["value"] >= 0.80,
    }
