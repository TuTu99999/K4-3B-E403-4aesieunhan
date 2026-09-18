from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.enums import ActionLabel, MessageType
from app.domain.models import LabeledRow, MessageRow
from app.eval.classifier_runner import _build_context_index


NOW = datetime(2026, 9, 18, 9, 0)


def message(message_id: str, minute: int, **overrides) -> MessageRow:
    values = {
        "msg_id": message_id,
        "guild": "G1",
        "channel": "C1",
        "author": "D1",
        "is_bot": False,
        "msg_type": MessageType.MESSAGE,
        "created_at_vn": NOW + timedelta(minutes=minute),
        "reply_to": None,
        "mentions_bot": False,
        "n_attachments": 0,
        "n_chars": 8,
        "content": f"message {message_id}",
    }
    values.update(overrides)
    return MessageRow.model_validate(values)


def labeled(message_id: str, minute: int) -> LabeledRow:
    return LabeledRow(
        **message(message_id, minute).model_dump(),
        label=ActionLabel.NORMAL,
        label_reason="test",
    )


def test_eval_context_is_bounded_scoped_and_supports_synthetic_cases() -> None:
    target = labeled("M00005", 5)
    synthetic = labeled("P_SYNTH_01", 6)
    messages = tuple(message(f"M0000{index}", index) for index in range(1, 9)) + (
        message("M99999", 4, channel="OTHER", content="must stay out"),
    )

    contexts = _build_context_index((target, synthetic), messages)

    before, after = contexts[target.offline_key]
    assert before == ("message M00002", "message M00003", "message M00004")
    assert after == ("message M00006", "message M00007", "message M00008")
    assert contexts[synthetic.offline_key] == ((), ())
