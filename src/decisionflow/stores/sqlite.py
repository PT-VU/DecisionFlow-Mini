from __future__ import annotations

from pathlib import Path

from ..audit import AuditLogger
from ..models import WorkflowResult


class SQLiteRunStore:
    """Run snapshots backed by the same SQLite file as the audit log."""

    def __init__(self, audit: AuditLogger | Path):
        self.audit = audit if isinstance(audit, AuditLogger) else AuditLogger(audit)

    def create(self, result: WorkflowResult) -> None:
        existing = self.find_by_idempotency_key(result.idempotency_key) if result.idempotency_key else None
        if existing:
            raise ValueError("idempotency key already exists")
        if self.exists(result.run_id):
            raise ValueError(f"run_id already exists: {result.run_id}")
        self.save(result)

    def get(self, run_id: str) -> WorkflowResult | None:
        return self.audit.snapshot(run_id)

    def save(self, result: WorkflowResult) -> None:
        self.audit.save_snapshot(result)

    def exists(self, run_id: str) -> bool:
        return self.get(run_id) is not None

    def find_by_idempotency_key(self, key: str) -> WorkflowResult | None:
        return self.audit.find_snapshot_by_idempotency_key(key)
