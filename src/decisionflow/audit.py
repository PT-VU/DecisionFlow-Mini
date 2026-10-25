from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from .models import AuditEvent, WorkflowResult, WorkflowStatus


class AuditLogger:
    def __init__(self, path: Path | None = None):
        self.path = path
        self._events: dict[str, list[AuditEvent]] = {}
        self._snapshots: dict[str, WorkflowResult] = {}
        if self.path and self.path.suffix == ".db":
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_events (
                        event_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        event_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute("CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_events(run_id, timestamp)")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_snapshots (
                        run_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        snapshot_json TEXT NOT NULL
                    )
                    """
                )

    def record(
        self,
        *,
        run_id: str,
        task_id: str,
        event_type: str,
        from_status: WorkflowStatus | None,
        to_status: WorkflowStatus,
        actor: str,
        payload: dict | None = None,
        finding_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=str(uuid4()),
            run_id=run_id,
            task_id=task_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            payload=payload or {},
            finding_refs=finding_refs or [],
            evidence_refs=evidence_refs or [],
        )
        self._events.setdefault(run_id, []).append(event)
        if self.path and self.path.suffix == ".db":
            with sqlite3.connect(self.path) as connection:
                connection.execute(
                    "INSERT INTO audit_events(event_id, run_id, task_id, timestamp, event_json) VALUES (?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.run_id,
                        event.task_id,
                        event.timestamp.isoformat(),
                        json.dumps(event.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
        elif self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n")
        return event

    def events(self, run_id: str) -> list[AuditEvent]:
        if self.path and self.path.suffix == ".db":
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    "SELECT event_json FROM audit_events WHERE run_id = ? ORDER BY timestamp, rowid", (run_id,)
                ).fetchall()
            return [AuditEvent.model_validate_json(row[0]) for row in rows]
        return list(self._events.get(run_id, []))

    def save_snapshot(self, result: WorkflowResult) -> None:
        """Persist the complete workflow state, separately from append-only events."""
        snapshot_json = result.model_dump_json()
        if self.path and self.path.suffix == ".db":
            with sqlite3.connect(self.path) as connection:
                connection.execute(
                    """
                    INSERT INTO workflow_snapshots(run_id, task_id, status, updated_at, snapshot_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        task_id = excluded.task_id,
                        status = excluded.status,
                        updated_at = excluded.updated_at,
                        snapshot_json = excluded.snapshot_json
                    """,
                    (
                        result.run_id,
                        result.ticket.task_id,
                        result.status.value,
                        result.audit_events[-1].timestamp.isoformat() if result.audit_events else "",
                        snapshot_json,
                    ),
                )
        else:
            self._snapshots[result.run_id] = result.model_copy(deep=True)

    def snapshot(self, run_id: str) -> WorkflowResult | None:
        """Load a workflow snapshot without reconstructing it from audit events."""
        if self.path and self.path.suffix == ".db":
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    "SELECT snapshot_json FROM workflow_snapshots WHERE run_id = ?", (run_id,)
                ).fetchone()
            return WorkflowResult.model_validate_json(row[0]) if row else None
        snapshot = self._snapshots.get(run_id)
        return snapshot.model_copy(deep=True) if snapshot else None

