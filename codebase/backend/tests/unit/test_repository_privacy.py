from __future__ import annotations

import subprocess
from pathlib import Path


def _repository_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def test_private_data_is_not_git_tracked() -> None:
    root = _repository_root()
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = {line.replace("\\", "/") for line in result.stdout.splitlines()}

    assert not any(
        path.startswith("K4-3B-Day05-06-AI-Product-Hackathon/") for path in tracked
    )
    assert ".env" not in tracked
    assert not any(path.startswith(".private/") for path in tracked)


def test_gitignore_contains_private_boundaries() -> None:
    root = _repository_root()
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")

    assert "/K4-3B-Day05-06-AI-Product-Hackathon/" in gitignore
    assert "/.private/" in gitignore
    assert ".env" in gitignore
