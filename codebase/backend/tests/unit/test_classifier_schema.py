import json

import pytest
from pydantic import ValidationError

from app.classifier.schema import ClassificationResponse


@pytest.mark.parametrize(
    "payload",
    [
        {"intent": "SUPPORT_QUESTION", "priority": "NORMAL", "confidence": 0.9},
        {"intent": "SUPPORT_QUESTION", "priority": "URGENT", "confidence": 1.0},
        {"intent": "NON_ACTIONABLE", "priority": None, "confidence": 0.8},
        {"intent": "UNCERTAIN", "priority": None, "confidence": 0.4},
    ],
)
def test_classifier_response_accepts_only_valid_combinations(payload) -> None:
    parsed = ClassificationResponse.model_validate_json(json.dumps(payload))

    assert parsed.confidence == payload["confidence"]


@pytest.mark.parametrize(
    "payload",
    [
        {"intent": "SUPPORT_QUESTION", "priority": None, "confidence": 0.9},
        {"intent": "NON_ACTIONABLE", "priority": "NORMAL", "confidence": 0.9},
        {"intent": "UNKNOWN", "priority": None, "confidence": 0.9},
        {"intent": "UNCERTAIN", "priority": None, "confidence": 1.1},
        {
            "intent": "NON_ACTIONABLE",
            "priority": None,
            "confidence": 0.9,
            "reason": "extra fields are forbidden",
        },
    ],
)
def test_classifier_response_rejects_invalid_or_extra_fields(payload) -> None:
    with pytest.raises(ValidationError):
        ClassificationResponse.model_validate_json(json.dumps(payload))


def test_classifier_response_rejects_markdown_wrapped_json() -> None:
    with pytest.raises(ValidationError):
        ClassificationResponse.model_validate_json(
            '```json\n{"intent":"NON_ACTIONABLE","priority":null,"confidence":0.9}\n```'
        )
