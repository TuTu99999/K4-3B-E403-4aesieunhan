"""Local-only HTTP server for the CP3 live AI demonstration."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import threading
import webbrowser
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.classifier.base import ClassifierProviderError
from app.classifier.prompt import PROMPT_VERSION
from app.classifier.provider import OpenAICompatibleClassifierProvider
from app.classifier.schema import (
    ClassificationIntent,
    ClassificationPriority,
    ClassificationRequest,
    ClassificationResponse,
)
from app.config import ConfigurationError, get_settings
from app.ingestion.normalizer import redact_content
from app.rules.risk_hints import detect_risk_hints

REPO_ROOT = Path(__file__).resolve().parents[4]
FRONTEND_DIR = REPO_ROOT / "codebase" / "frontend" / "dist"
GOLDEN_SUMMARY = REPO_ROOT / "eval" / "results" / "cp3-run-1-summary.json"
TRACE_PATH = REPO_ROOT / "eval" / "traces" / "cp3-live-traces.jsonl"
MAX_REQUEST_BYTES = 12_000
MAX_MESSAGE_CHARS = 2_000
_TRACE_LOCK = threading.Lock()

DEMO_CASES: tuple[dict[str, object], ...] = (
    {
        "id": "urgent-submit",
        "title": "Không thể nộp bài",
        "message": "Còn 5 phút hết hạn mà hệ thống báo 500, em không submit được ạ",
        "expected": "URGENT",
        "age_minutes": 12,
        "tone": "urgent",
    },
    {
        "id": "normal-material",
        "title": "Xin tài liệu buổi học",
        "message": "Cho em xin lại slide buổi 3 với ạ",
        "expected": "NORMAL",
        "age_minutes": 64,
        "tone": "normal",
    },
    {
        "id": "ignore-thanks",
        "title": "Lời cảm ơn",
        "message": "Em làm được rồi, cảm ơn TA nhiều ạ 😄",
        "expected": "IGNORE",
        "age_minutes": 70,
        "tone": "ignore",
    },
    {
        "id": "urgent-session",
        "title": "Bị văng khỏi buổi học",
        "message": "Em vào mà cứ bị out ra thì phải làm sao ạ?",
        "expected": "URGENT",
        "age_minutes": 16,
        "tone": "urgent",
    },
)


def _label_for(response: ClassificationResponse, threshold: float) -> str:
    if response.confidence < threshold or response.intent is ClassificationIntent.UNCERTAIN:
        return "NEEDS_REVIEW"
    if response.intent is ClassificationIntent.NON_ACTIONABLE:
        return "IGNORE"
    if response.priority is ClassificationPriority.URGENT:
        return "URGENT"
    return "NORMAL"


def _write_trace(payload: dict[str, object]) -> None:
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with _TRACE_LOCK, TRACE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(serialized + "\n")


async def classify_live(
    message: str,
    *,
    age_minutes: int,
    has_attachment: bool,
) -> dict[str, object]:
    settings = get_settings()
    api_key, base_url, model = settings.require_classifier_config()
    safe_message = redact_content(message)
    risk_hints = detect_risk_hints(safe_message)
    request = ClassificationRequest(
        message=safe_message,
        context_before=(),
        context_after=(),
        age_minutes=age_minutes,
        has_attachment=has_attachment,
        risk_hints=risk_hints,
        prompt_version=PROMPT_VERSION,
    )
    provider = OpenAICompatibleClassifierProvider(
        api_key,
        base_url,
        model,
        timeout_seconds=settings.classifier_timeout_seconds,
        retry_limit=settings.classifier_retry_limit,
    )
    try:
        provider_result = await provider.classify(request)
    finally:
        await provider.aclose()

    response = provider_result.response
    label = _label_for(response, settings.classifier_confidence_threshold)
    trace_id = "tr_" + hashlib.sha256(
        (
            request.canonical_hash()
            + datetime.now(timezone.utc).isoformat(timespec="microseconds")
        ).encode("utf-8")
    ).hexdigest()[:12]
    trace = {
        "trace_id": trace_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "request_hash": request.canonical_hash(),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "result": label,
        "intent": response.intent.value,
        "priority": response.priority.value if response.priority else None,
        "confidence": response.confidence,
        "latency_ms": provider_result.latency_ms,
        "provider_attempts": provider_result.provider_attempts,
        "token_usage": provider_result.token_usage,
        "live_call": True,
        "contains_raw_message": False,
    }
    _write_trace(trace)
    return {
        **trace,
        "risk_hints": list(risk_hints),
        "threshold": settings.classifier_confidence_threshold,
    }


class DemoRequestHandler(SimpleHTTPRequestHandler):
    server_version = "DiscordRadar/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def _json_response(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            settings = get_settings()
            try:
                _, _, model = settings.require_classifier_config()
                self._json_response(
                    {
                        "status": "ready",
                        "provider": "9Router",
                        "model": model,
                        "prompt_version": PROMPT_VERSION,
                    }
                )
            except ConfigurationError:
                self._json_response(
                    {"status": "not_configured", "error": "CLASSIFIER_NOT_CONFIGURED"},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            return
        if path == "/api/demo-cases":
            self._json_response({"cases": DEMO_CASES})
            return
        if path == "/api/evaluation":
            if not GOLDEN_SUMMARY.is_file():
                self._json_response(
                    {"error": "EVALUATION_REPORT_NOT_FOUND"},
                    HTTPStatus.NOT_FOUND,
                )
                return
            self._json_response(json.loads(GOLDEN_SUMMARY.read_text(encoding="utf-8")))
            return
        if path == "/api/traces/latest":
            self._json_response({"traces": self._latest_traces()})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/classify":
            self._json_response({"error": "NOT_FOUND"}, HTTPStatus.NOT_FOUND)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self._json_response({"error": "INVALID_REQUEST_SIZE"}, HTTPStatus.BAD_REQUEST)
            return
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._json_response({"error": "INVALID_REQUEST_SIZE"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
            message = str(payload.get("message", "")).strip()
            age_minutes = int(payload.get("age_minutes", 60))
            has_attachment_value = payload.get("has_attachment", False)
            if not isinstance(has_attachment_value, bool):
                raise TypeError("has_attachment must be a boolean")
            has_attachment = has_attachment_value
        except (json.JSONDecodeError, TypeError, ValueError):
            self._json_response({"error": "INVALID_JSON"}, HTTPStatus.BAD_REQUEST)
            return
        if not message or len(message) > MAX_MESSAGE_CHARS or not 0 <= age_minutes <= 10_080:
            self._json_response({"error": "INVALID_INPUT"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            result = asyncio.run(
                classify_live(
                    message,
                    age_minutes=age_minutes,
                    has_attachment=has_attachment,
                )
            )
        except ConfigurationError:
            self._json_response(
                {"error": "CLASSIFIER_NOT_CONFIGURED"},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        except ClassifierProviderError as exc:
            self._json_response(
                {"error": exc.code, "retryable": exc.retryable},
                HTTPStatus.BAD_GATEWAY,
            )
            return
        self._json_response(result)

    @staticmethod
    def _latest_traces(limit: int = 5) -> list[dict[str, object]]:
        if not TRACE_PATH.is_file():
            return []
        lines = TRACE_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
        traces: list[dict[str, object]] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                traces.append(payload)
        return traces

    def log_message(self, format_string: str, *args: object) -> None:
        del format_string, args


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local CP3 demonstration UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not FRONTEND_DIR.is_dir():
        raise SystemExit(f"Frontend assets are missing: {FRONTEND_DIR}")
    address = f"http://{args.host}:{args.port}"
    server = ThreadingHTTPServer((args.host, args.port), DemoRequestHandler)
    print("CP3 demo is ready.")
    print(f"Open: {address}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.6, partial(webbrowser.open, address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCP3 demo stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
