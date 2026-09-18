"""Run the locked public CP3 golden set against the live classifier provider."""

from __future__ import annotations

import asyncio
import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.classifier.base import ClassifierProviderError, ClassifierSchemaError
from app.classifier.prompt import PROMPT_VERSION, build_chat_messages
from app.classifier.provider import OpenAICompatibleClassifierProvider
from app.classifier.schema import (
    ClassificationIntent,
    ClassificationPriority,
    ClassificationRequest,
    ClassificationResponse,
)
from app.config import get_settings
from app.eval.metrics import compute_classification_metrics, quality_bar
from app.ingestion.normalizer import redact_content
from app.rules.risk_hints import detect_risk_hints

LABEL_NAMES = {0: "IGNORE", 1: "NORMAL", 2: "URGENT", 3: "NEEDS_REVIEW"}
REQUIRED_HARD_BUCKETS = {
    "hard_source_truth",
    "hard_ambiguous",
    "hard_out_of_scope",
    "hard_domain_specific",
}


@dataclass(frozen=True, slots=True)
class Cp3Case:
    case_id: str
    message: str
    expected_label: int
    expected_name: str
    bucket: str
    origin: str
    has_attachment: bool
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Cp3Outcome:
    case: Cp3Case
    predicted_label: int
    response: ClassificationResponse | None
    raw_response: str | None
    latency_ms: int
    token_usage: dict[str, int]
    provider_attempts: int
    error_code: str | None
    request: ClassificationRequest

    @property
    def passed(self) -> bool:
        return self.case.expected_label == self.predicted_label


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_cases(path: Path) -> list[Cp3Case]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("CP3 golden set must be a JSON array.")
    cases: list[Cp3Case] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Every CP3 case must be an object.")
        expected_label = int(item["expected_label"])
        expected_name = str(item["expected_name"])
        if expected_label not in LABEL_NAMES or LABEL_NAMES[expected_label] != expected_name:
            raise ValueError(f"Invalid label mapping for {item.get('case_id', '<unknown>')}.")
        cases.append(
            Cp3Case(
                case_id=str(item["case_id"]),
                message=str(item["message"]),
                expected_label=expected_label,
                expected_name=expected_name,
                bucket=str(item["bucket"]),
                origin=str(item["origin"]),
                has_attachment=bool(item.get("has_attachment", False)),
                metadata={
                    key: value
                    for key, value in item.items()
                    if key
                    not in {
                        "case_id",
                        "message",
                        "expected_label",
                        "expected_name",
                        "bucket",
                        "origin",
                        "has_attachment",
                    }
                },
            )
        )
    _validate_coverage(cases)
    return cases


def _validate_coverage(cases: list[Cp3Case]) -> None:
    if len(cases) < 20:
        raise ValueError("CP3 golden set requires at least 20 cases.")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("CP3 case IDs must be unique.")
    bucket_counts = Counter(case.bucket for case in cases)
    for bucket in REQUIRED_HARD_BUCKETS:
        if bucket_counts[bucket] < 2:
            raise ValueError(f"Bucket {bucket} requires at least 2 cases.")
    if not 8 <= bucket_counts["common"] <= 10:
        raise ValueError("CP3 golden set requires 8-10 common cases.")
    if not 2 <= bucket_counts["rare"] <= 4:
        raise ValueError("CP3 golden set requires 2-4 rare cases.")
    real_count = sum(case.origin == "real_chatlog_paraphrase" for case in cases)
    if real_count < 10:
        raise ValueError("At least 10 cases must be developed from real chatlog data.")


def _prediction_label(response: ClassificationResponse | None, threshold: float) -> int:
    if response is None or response.confidence < threshold:
        return 3
    if response.intent is ClassificationIntent.UNCERTAIN:
        return 3
    if response.intent is ClassificationIntent.NON_ACTIONABLE:
        return 0
    if response.priority is ClassificationPriority.URGENT:
        return 2
    return 1


def _request_for(case: Cp3Case) -> ClassificationRequest:
    message = redact_content(case.message)
    return ClassificationRequest(
        message=message,
        context_before=(),
        context_after=(),
        age_minutes=60,
        has_attachment=case.has_attachment,
        risk_hints=detect_risk_hints(message),
        prompt_version=PROMPT_VERSION,
    )


async def _run_case(
    case: Cp3Case,
    provider: OpenAICompatibleClassifierProvider,
    *,
    threshold: float,
    semaphore: asyncio.Semaphore,
) -> Cp3Outcome:
    request = _request_for(case)
    response: ClassificationResponse | None = None
    raw_response: str | None = None
    latency_ms = 0
    token_usage: dict[str, int] = {}
    provider_attempts = 0
    error_code: str | None = None
    async with semaphore:
        try:
            result = await provider.classify(request)
            response = result.response
            raw_response = result.raw_response
            latency_ms = result.latency_ms
            token_usage = result.token_usage
            provider_attempts = result.provider_attempts
        except (ClassifierProviderError, ClassifierSchemaError) as exc:
            latency_ms = exc.latency_ms
            provider_attempts = exc.provider_attempts
            error_code = exc.code
    return Cp3Outcome(
        case=case,
        predicted_label=_prediction_label(response, threshold),
        response=response,
        raw_response=raw_response,
        latency_ms=latency_ms,
        token_usage=token_usage,
        provider_attempts=provider_attempts,
        error_code=error_code,
        request=request,
    )


def _failure_category(outcome: Cp3Outcome) -> str:
    if outcome.passed:
        return "none"
    expected = outcome.case.expected_label
    predicted = outcome.predicted_label
    if outcome.error_code:
        return "provider_or_schema_error"
    if expected == 2 and predicted != 2:
        return "missed_urgent"
    if expected == 3 and predicted != 3:
        return "overconfident_on_missing_context"
    if expected == 0 and predicted in {1, 2}:
        return "false_positive_notification"
    if expected in {1, 2} and predicted == 0:
        return "missed_actionable"
    if expected == 1 and predicted == 2:
        return "priority_over_escalation"
    return "label_mismatch"


def _failure_analysis(outcome: Cp3Outcome) -> str:
    category = _failure_category(outcome)
    if category == "none":
        return "Kết quả khớp nhãn đã review."
    explanations = {
        "provider_or_schema_error": (
            "Không có output hợp lệ để chấm vì provider hoặc schema thất bại."
        ),
        "missed_urgent": (
            "Model bỏ sót tín hiệu chặn thao tác hoặc giới hạn thời gian; có nguy cơ trễ hỗ trợ."
        ),
        "overconfident_on_missing_context": (
            "Model kết luận khi câu hỏi thiếu đối tượng/ngữ cảnh thay vì chuyển người review; "
            "cần bổ sung context hoặc rule nhận diện câu tham chiếu mơ hồ."
        ),
        "false_positive_notification": (
            "Model biến hội thoại phiếm thành việc cho TA, có nguy cơ tạo alert fatigue."
        ),
        "missed_actionable": (
            "Model bỏ qua một yêu cầu cần TA xử lý; cần kiểm tra cách diễn đạt ngầm."
        ),
        "priority_over_escalation": (
            "Model nâng câu hỏi thông thường thành khẩn dù không có tắc nghẽn đang xảy ra."
        ),
        "label_mismatch": "Nhãn model khác chuẩn review; cần đối chiếu lại rubric và output thô.",
    }
    return explanations[category]


def _case_rows(outcomes: list[Cp3Outcome]) -> list[dict[str, object]]:
    return [
        {
            "case_id": outcome.case.case_id,
            "bucket": outcome.case.bucket,
            "origin": outcome.case.origin,
            "expected": outcome.case.expected_name,
            "predicted": LABEL_NAMES[outcome.predicted_label],
            "passed": outcome.passed,
            "confidence": outcome.response.confidence if outcome.response else "",
            "latency_ms": outcome.latency_ms,
            "provider_attempts": outcome.provider_attempts,
            "error_code": outcome.error_code or "",
            "failure_category": _failure_category(outcome),
            "failure_analysis": _failure_analysis(outcome),
        }
        for outcome in outcomes
    ]


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_traces(path: Path, outcomes: list[Cp3Outcome], model: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for outcome in outcomes:
            trace = {
                "case_id": outcome.case.case_id,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "request_hash": outcome.request.canonical_hash(),
                "prompt_input": build_chat_messages(outcome.request),
                "raw_model_response": outcome.raw_response,
                "parsed_response": (
                    outcome.response.model_dump(mode="json") if outcome.response else None
                ),
                "latency_ms": outcome.latency_ms,
                "provider_attempts": outcome.provider_attempts,
                "error_code": outcome.error_code,
            }
            handle.write(json.dumps(trace, ensure_ascii=False, sort_keys=True) + "\n")


def _write_analysis(path: Path, summary: dict[str, object], rows: list[dict[str, object]]) -> None:
    failures = [row for row in rows if not row["passed"]]
    metrics = summary["metrics"]
    assert isinstance(metrics, dict)
    lines = [
        "# CP3 — Phân tích lượt chạy đầu",
        "",
        f"- Tổng số case: **{summary['case_count']}**",
        f"- Đạt: **{summary['passed_count']}**",
        f"- Không đạt: **{summary['failed_count']}**",
        f"- Tỷ lệ đạt: **{float(metrics['accuracy']) * 100:.1f}%**",
        f"- URGENT recall: **{metrics['urgent_recall']['found']}/{metrics['urgent_recall']['total']}**",
        f"- Provider/schema error: **{summary['provider_errors']}**",
        "- Chế độ chạy: **AI thật, không cache**",
        "",
        "## Các trường hợp sai lệch",
        "",
    ]
    if not failures:
        lines.append("Không có case sai trong lượt chạy này; bảng CSV vẫn giữ đủ toàn bộ case.")
    else:
        for row in failures:
            lines.append(
                f"- `{row['case_id']}`: kỳ vọng `{row['expected']}`, nhận "
                f"`{row['predicted']}` — `{row['failure_category']}`. "
                f"{row['failure_analysis']}"
            )
    lines.extend(
        [
            "",
            "## Giới hạn diễn giải",
            "",
            "Đây là lượt đo trên golden set do nhóm tự xây và review, không phải blind benchmark. "
            "Case phát triển từ chatlog đã được diễn đạt lại để không công khai nội dung Discord gốc.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run() -> tuple[dict[str, object], list[dict[str, object]]]:
    root = _repo_root()
    cases = _load_cases(root / "eval" / "cp3_golden_set.json")
    settings = get_settings()
    api_key, base_url, model = settings.require_classifier_config()
    provider = OpenAICompatibleClassifierProvider(
        api_key,
        base_url,
        model,
        timeout_seconds=settings.classifier_timeout_seconds,
        retry_limit=settings.classifier_retry_limit,
    )
    semaphore = asyncio.Semaphore(settings.classifier_concurrency)
    try:
        outcomes = list(
            await asyncio.gather(
                *(
                    _run_case(
                        case,
                        provider,
                        threshold=settings.classifier_confidence_threshold,
                        semaphore=semaphore,
                    )
                    for case in cases
                )
            )
        )
    finally:
        await provider.aclose()

    expected = [outcome.case.expected_label for outcome in outcomes]
    predicted = [outcome.predicted_label for outcome in outcomes]
    metrics = compute_classification_metrics(
        expected,
        predicted,
        latencies_ms=[outcome.latency_ms for outcome in outcomes],
        total_tokens=sum(
            outcome.token_usage.get("total_tokens", 0) for outcome in outcomes
        ),
    )
    rows = _case_rows(outcomes)
    summary: dict[str, object] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": "cp3_run_1",
        "run_mode": "live_ai_no_cache",
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "case_count": len(cases),
        "passed_count": sum(outcome.passed for outcome in outcomes),
        "failed_count": sum(not outcome.passed for outcome in outcomes),
        "provider_errors": sum(outcome.error_code is not None for outcome in outcomes),
        "taxonomy_counts": dict(sorted(Counter(case.bucket for case in cases).items())),
        "real_chatlog_derived_count": sum(
            case.origin == "real_chatlog_paraphrase" for case in cases
        ),
        "metrics": metrics,
        "quality_bar": quality_bar(metrics),
        "privacy": {
            "raw_discord_content": False,
            "message_ids": False,
            "public_cases_are_paraphrased_or_constructed": True,
        },
    }
    output_dir = root / "eval" / "results"
    _write_json(output_dir / "cp3-run-1-summary.json", summary)
    _write_csv(output_dir / "cp3-run-1-cases.csv", rows)
    _write_traces(output_dir / "cp3-run-1-traces.jsonl", outcomes, model)
    _write_analysis(output_dir / "cp3-run-1-analysis.md", summary, rows)
    return summary, rows


def main() -> int:
    summary, _ = asyncio.run(run())
    metrics = summary["metrics"]
    assert isinstance(metrics, dict)
    print(
        f"CP3 run 1: {summary['passed_count']}/{summary['case_count']} passed "
        f"({float(metrics['accuracy']) * 100:.1f}%)."
    )
    print(
        "URGENT recall: "
        f"{metrics['urgent_recall']['found']}/{metrics['urgent_recall']['total']}."
    )
    print(f"Provider errors: {summary['provider_errors']}.")
    print(f"Results: {_repo_root() / 'eval' / 'results'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
