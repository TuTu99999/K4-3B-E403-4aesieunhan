"""Conservative lexical hints used only to enter the classifier fast lane."""

from __future__ import annotations

import re

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "DEADLINE_RISK",
        re.compile(r"(?i)\b(deadline|hạn\s*nộp|han\s*nop|sắp\s*hết\s*giờ|sap\s*het\s*gio)\b"),
    ),
    (
        "SUBMISSION_BLOCKED",
        re.compile(
            r"(?i)\b(không|ko|khong)\s+(?:thể\s+)?(?:submit|nộp|nop)\s+(?:được|duoc)\b"
        ),
    ),
    (
        "ACCOUNT_BLOCKED",
        re.compile(
            r"(?i)\b(không|ko|khong)\s+(?:đăng\s*nhập|dang\s*nhap|login)\b|"
            r"\b(tài\s*khoản|tai\s*khoan|account)\s+(?:bị\s+)?(?:khóa|khoa|locked)\b"
        ),
    ),
    (
        "SESSION_ACCESS_BLOCKED",
        re.compile(
            r"(?i)\b(không|ko|khong)\s+vào\s+(?:được\s+)?(?:lớp|lop|workshop|live|zoom|meet)\b"
        ),
    ),
    (
        "SESSION_ACCESS_UNSTABLE",
        re.compile(
            r"(?i)\b(?:bị\s+)?(?:out|văng|vang)\s+(?:ra\s+)?(?:liên\s+tục|lien\s+tuc|hoài|hoai)?\b|"
            r"\bvào\s+(?:mà\s+)?cứ\s+(?:bị\s+)?out\b"
        ),
    ),
    (
        "SYSTEM_FAILURE",
        re.compile(r"(?i)\b(system\s+down|server\s+down|5\d\d|mất\s+dữ\s+liệu|mat\s+du\s+lieu)\b"),
    ),
)


def detect_risk_hints(content_redacted: str) -> tuple[str, ...]:
    """Return reason codes only; never copy matched user content into audit logs."""

    return tuple(code for code, pattern in _PATTERNS if pattern.search(content_redacted))
