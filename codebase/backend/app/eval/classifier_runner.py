"""Offline golden/hard-case evaluation for the strict classifier contract."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.classifier.base import ClassifierProviderError, ClassifierSchemaError
from app.classifier.prompt import PROMPT_VERSION
from app.classifier.provider import OpenAICompatibleClassifierProvider
from app.classifier.schema import (
    ClassificationIntent,
    ClassificationPriority,
    ClassificationRequest,
    ClassificationResponse,
)
from app.config import get_settings
from app.eval.metrics import compute_classification_metrics, quality_bar
from app.ingestion.csv_loader import load_labeled_rows
from app.domain.models import LabeledRow, MessageRow
from app.ingestion.csv_loader import load_message_rows
from app.ingestion.normalizer import redact_content
from app.rules.risk_hints import detect_risk_hints


@dataclass(frozen=True, slots=True)
class EvalCase:
    case_key: str
    content: str
    expected_label: int
    has_attachment: bool
    source_type: str
    context_before: tuple[str, ...] = ()
    context_after: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvalPrediction:
    case_hash: str
    expected_label: int
    predicted_label: int
    response: ClassificationResponse | None
    latency_ms: int
    token_usage: dict[str, int]
    error_code: str | None
    cache_hit: bool


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _parse_args() -> argparse.Namespace:
    root = _repo_root()
    parser = argparse.ArgumentParser(description="Run classifier evaluation without raw output.")
    parser.add_argument("--dataset", choices=("golden", "hard"), default="golden")
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--private-output", type=Path)
    parser.add_argument(
        "--cache",
        type=Path,
        default=root / ".private" / "eval" / "classifier-response-cache.json",
    )
    parser.add_argument("--no-cache", action="store_true")
    return parser.parse_args()


def _load_cases(dataset: str) -> list[EvalCase]:
    settings = get_settings()
    if dataset == "golden":
        path, messages_path = settings.require_paths(
            "private_golden_csv", "private_messages_csv"
        )
        rows = load_labeled_rows(path).rows
        messages = load_message_rows(messages_path).rows
        contexts = _build_context_index(rows, messages)
        return [
            EvalCase(
                case_key=row.offline_key,
                content=row.content,
                expected_label=int(row.label),
                has_attachment=row.n_attachments > 0,
                source_type="real_observed",
                context_before=contexts[row.offline_key][0],
                context_after=contexts[row.offline_key][1],
            )
            for row in rows
        ]

    path = _repo_root() / "eval" / "fixtures" / "classifier_hard_cases.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for item in payload:
        cases.append(
            EvalCase(
                case_key=str(item["case_id"]),
                content=str(item["message"]),
                expected_label=int(item["expected_label"]),
                has_attachment=False,
                source_type="constructed_reviewed",
            )
        )
    return cases


def _build_context_index(
    labeled_rows: tuple[LabeledRow, ...],
    messages: tuple[MessageRow, ...],
    *,
    context_limit: int = 3,
    window_minutes: int = 30,
) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """Reconstruct the same bounded channel context used by the runtime classifier."""

    by_scope: dict[tuple[str, str], list[MessageRow]] = {}
    for message in messages:
        by_scope.setdefault((message.guild, message.channel), []).append(message)
    for scoped_messages in by_scope.values():
        scoped_messages.sort(key=lambda item: (item.created_at_vn, item.msg_id))

    window = timedelta(minutes=window_minutes)
    result: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for labeled in labeled_rows:
        scoped_messages = by_scope.get((labeled.guild, labeled.channel), [])
        position = next(
            (
                index
                for index, message in enumerate(scoped_messages)
                if message.msg_id == labeled.msg_id
            ),
            None,
        )
        if position is None:
            result[labeled.offline_key] = ((), ())
            continue
        lower = labeled.created_at_vn - window
        upper = labeled.created_at_vn + window
        before = _select_eval_context(
            [
                message
                for message in scoped_messages[:position]
                if message.created_at_vn >= lower
            ][-context_limit:]
        )
        after = _select_eval_context(
            [
                message
                for message in scoped_messages[position + 1 :]
                if message.created_at_vn <= upper
            ][:context_limit]
        )
        result[labeled.offline_key] = (before, after)
    return result


def _select_eval_context(messages: list[MessageRow]) -> tuple[str, ...]:
    return tuple(
        redact_content(message.content)
        for message in messages
        if message.content.strip() and not (message.is_bot and len(message.content) > 500)
    )


def _load_cache(path: Path, enabled: bool) -> dict[str, dict[str, Any]]:
    if not enabled or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _prediction_label(
    response: ClassificationResponse | None,
    *,
    threshold: float,
) -> int:
    if response is None or response.confidence < threshold:
        return 3
    if response.intent is ClassificationIntent.UNCERTAIN:
        return 3
    if response.intent is ClassificationIntent.NON_ACTIONABLE:
        return 0
    if response.priority is ClassificationPriority.URGENT:
        return 2
    return 1


def _request_for_case(case: EvalCase) -> ClassificationRequest:
    message = redact_content(case.content)
    return ClassificationRequest(
        message=message,
        context_before=case.context_before,
        context_after=case.context_after,
        age_minutes=60,
        has_attachment=case.has_attachment,
        risk_hints=detect_risk_hints(message),
        prompt_version=PROMPT_VERSION,
    )


async def _run_case(
    case: EvalCase,
    provider: OpenAICompatibleClassifierProvider,
    *,
    threshold: float,
    schema_retry_limit: int,
    semaphore: asyncio.Semaphore,
    cache: dict[str, dict[str, Any]],
    use_cache: bool,
) -> tuple[EvalPrediction, str, dict[str, Any] | None]:
    request = _request_for_case(case)
    cache_material = f"{provider.model_name}:{request.canonical_hash()}"
    cache_key = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()
    case_hash = hashlib.sha256(case.case_key.encode("utf-8")).hexdigest()
    cached = cache.get(cache_key) if use_cache else None
    if cached:
        try:
            response = ClassificationResponse.model_validate_json(
                json.dumps(cached["response"])
            )
            prediction = EvalPrediction(
                case_hash,
                case.expected_label,
                _prediction_label(response, threshold=threshold),
                response,
                int(cached.get("latency_ms", 0)),
                {
                    key: int(value)
                    for key, value in cached.get("token_usage", {}).items()
                    if isinstance(value, int)
                },
                None,
                True,
            )
            return prediction, cache_key, None
        except (KeyError, ValueError, TypeError):
            pass

    error_code: str | None = None
    response: ClassificationResponse | None = None
    latency_ms = 0
    token_usage: dict[str, int] = {}
    async with semaphore:
        for schema_attempt in range(schema_retry_limit + 1):
            try:
                result = await provider.classify(request)
                response = result.response
                latency_ms = result.latency_ms
                token_usage = result.token_usage
                break
            except ClassifierSchemaError as exc:
                error_code = exc.code
                latency_ms += exc.latency_ms
                if schema_attempt >= schema_retry_limit:
                    break
            except ClassifierProviderError as exc:
                error_code = exc.code
                latency_ms += exc.latency_ms
                break

    prediction = EvalPrediction(
        case_hash,
        case.expected_label,
        _prediction_label(response, threshold=threshold),
        response,
        latency_ms,
        token_usage,
        error_code if response is None else None,
        False,
    )
    cache_value = None
    if response is not None:
        cache_value = {
            "response": response.model_dump(mode="json"),
            "latency_ms": latency_ms,
            "token_usage": token_usage,
        }
    return prediction, cache_key, cache_value


async def run_evaluation(
    dataset: str,
    *,
    cache_path: Path,
    use_cache: bool,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    settings = get_settings()
    api_key, base_url, model = settings.require_classifier_config()
    cases = _load_cases(dataset)
    cache = _load_cache(cache_path, use_cache)
    provider = OpenAICompatibleClassifierProvider(
        api_key,
        base_url,
        model,
        timeout_seconds=settings.classifier_timeout_seconds,
        retry_limit=settings.classifier_retry_limit,
    )
    semaphore = asyncio.Semaphore(settings.classifier_concurrency)
    try:
        outputs = await asyncio.gather(
            *(
                _run_case(
                    case,
                    provider,
                    threshold=settings.classifier_confidence_threshold,
                    schema_retry_limit=settings.classifier_schema_retry_limit,
                    semaphore=semaphore,
                    cache=cache,
                    use_cache=use_cache,
                )
                for case in cases
            )
        )
    finally:
        await provider.aclose()

    predictions: list[EvalPrediction] = []
    for prediction, cache_key, cache_value in outputs:
        predictions.append(prediction)
        if cache_value is not None:
            cache[cache_key] = cache_value
    if use_cache:
        _save_json(cache_path, cache)

    expected = [item.expected_label for item in predictions]
    predicted = [item.predicted_label for item in predictions]
    latencies = [item.latency_ms for item in predictions]
    total_tokens = sum(
        item.token_usage.get("total_tokens", 0) for item in predictions
    )
    metrics = compute_classification_metrics(
        expected,
        predicted,
        latencies_ms=latencies,
        total_tokens=total_tokens,
    )
    keyword_predictions = [
        2 if detect_risk_hints(redact_content(case.content)) else 0 for case in cases
    ]
    keyword_metrics = compute_classification_metrics(expected, keyword_predictions)
    always_ignore_accuracy = sum(label == 0 for label in expected) / len(expected)
    summary: dict[str, object] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset,
        "source_type": cases[0].source_type if cases else "unknown",
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "confidence_threshold": settings.classifier_confidence_threshold,
        "case_count": len(cases),
        "cache_hits": sum(item.cache_hit for item in predictions),
        "provider_errors": sum(item.error_code is not None for item in predictions),
        "metrics": metrics,
        "quality_bar": quality_bar(metrics),
        "baselines": {
            "master_all_ignore_accuracy_reference": 0.878,
            "dataset_all_ignore_accuracy": round(always_ignore_accuracy, 4),
            "keyword_urgent": keyword_metrics,
        },
        "privacy": {
            "contains_raw_content": False,
            "contains_message_ids": False,
        },
    }
    private_rows = [
        {
            "case_hash": item.case_hash,
            "expected_label": item.expected_label,
            "predicted_label": item.predicted_label,
            "intent": item.response.intent.value if item.response else None,
            "priority": (
                item.response.priority.value
                if item.response and item.response.priority
                else None
            ),
            "confidence": item.response.confidence if item.response else None,
            "latency_ms": item.latency_ms,
            "token_usage": item.token_usage,
            "error_code": item.error_code,
            "cache_hit": item.cache_hit,
        }
        for item in predictions
    ]
    return summary, private_rows


def main() -> int:
    args = _parse_args()
    root = _repo_root()
    summary_output = args.summary_output or (
        root / "eval" / "results" / f"phase3-{args.dataset}-summary.json"
    )
    private_output = args.private_output or (
        root / ".private" / "eval" / f"phase3-{args.dataset}-predictions.json"
    )
    summary, private_rows = asyncio.run(
        run_evaluation(
            args.dataset,
            cache_path=args.cache,
            use_cache=not args.no_cache,
        )
    )
    _save_json(summary_output, summary)
    _save_json(private_output, private_rows)
    metrics = summary["metrics"]
    assert isinstance(metrics, dict)
    print(f"Phase 3 {args.dataset} evaluation completed: {summary['case_count']} cases")
    print(f"Accuracy: {metrics['accuracy']}")
    print(f"Macro-F1: {metrics['macro_f1']}")
    print(f"Urgent recall: {metrics['urgent_recall']}")
    print(f"Actionable recall: {metrics['actionable_recall']}")
    print(f"Notification precision: {metrics['notification_intent_precision']}")
    print(f"Public summary: {summary_output}")
    print(f"Private predictions: {private_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
