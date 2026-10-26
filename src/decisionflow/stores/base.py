from __future__ import annotations

from typing import Protocol

from ..models import AuditEvent, WorkflowResult


class RunStore(Protocol):
    def create(self, result: WorkflowResult) -> None: ...

    def get(self, run_id: str) -> WorkflowResult | None: ...

    def save(self, result: WorkflowResult) -> None: ...

    def exists(self, run_id: str) -> bool: ...

    def find_by_idempotency_key(self, key: str) -> WorkflowResult | None: ...


class AuditStore(Protocol):
    def append(self, event: AuditEvent) -> AuditEvent: ...

    def list_events(self, run_id: str) -> list[AuditEvent]: ...

