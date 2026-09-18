from __future__ import annotations

import json

from app.classifier.schema import (
    ClassificationIntent,
    ClassificationPriority,
    ClassificationResponse,
)
from app.demo import server


def _response(
    intent: ClassificationIntent,
    *,
    priority: ClassificationPriority | None,
    confidence: float,
) -> ClassificationResponse:
    return ClassificationResponse(
        intent=intent,
        priority=priority,
        confidence=confidence,
    )


def test_label_for_maps_supported_decisions() -> None:
    urgent = _response(
        ClassificationIntent.SUPPORT_QUESTION,
        priority=ClassificationPriority.URGENT,
        confidence=0.95,
    )
    normal = _response(
        ClassificationIntent.SUPPORT_QUESTION,
        priority=ClassificationPriority.NORMAL,
        confidence=0.91,
    )
    ignored = _response(
        ClassificationIntent.NON_ACTIONABLE,
        priority=None,
        confidence=0.98,
    )

    assert server._label_for(urgent, 0.7) == "URGENT"
    assert server._label_for(normal, 0.7) == "NORMAL"
    assert server._label_for(ignored, 0.7) == "IGNORE"


def test_label_for_routes_low_confidence_and_uncertain_to_review() -> None:
    low_confidence = _response(
        ClassificationIntent.SUPPORT_QUESTION,
        priority=ClassificationPriority.NORMAL,
        confidence=0.69,
    )
    uncertain = _response(
        ClassificationIntent.UNCERTAIN,
        priority=None,
        confidence=0.99,
    )

    assert server._label_for(low_confidence, 0.7) == "NEEDS_REVIEW"
    assert server._label_for(uncertain, 0.7) == "NEEDS_REVIEW"


def test_write_trace_does_not_require_raw_content(tmp_path, monkeypatch) -> None:
    trace_path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(server, "TRACE_PATH", trace_path)
    payload = {
        "trace_id": "tr_test",
        "request_hash": "hash-only",
        "contains_raw_message": False,
    }

    server._write_trace(payload)

    stored = json.loads(trace_path.read_text(encoding="utf-8"))
    assert stored == payload
    assert "message" not in stored
