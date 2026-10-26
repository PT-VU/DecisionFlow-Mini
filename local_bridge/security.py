from __future__ import annotations

from pathlib import Path


ALLOWED_TASK_TYPES = frozenset({"text_completion", "inspect_project", "run_tests"})


def ensure_allowed_task(task_type: str) -> None:
    if task_type not in ALLOWED_TASK_TYPES:
        raise ValueError("task type is not allow-listed")


def resolve_workspace(root: Path, requested: str) -> Path:
    if requested in {"", ".", "project"}:
        requested = "."
    candidate = (root / requested).resolve()
    root = root.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("workspace path escapes configured root")
    return candidate


def redact_output(value: str, *, limit: int = 12_000) -> str:
    text = value[:limit]
    for token in ("api_key", "API_KEY", "authorization", "Authorization", "token"):
        text = text.replace(token, "[REDACTED]")
    return text
