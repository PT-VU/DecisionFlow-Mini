from __future__ import annotations

from copy import deepcopy

from ..models import AuditEvent, WorkflowResult


class MemoryRunStore:
    """Deterministic in-process store used by tests and local mock mode."""

    def __init__(self) -> None:
        self._items: dict[str, WorkflowResult] = {}
        self._idempotency: dict[str, str] = {}

    def create(self, result: WorkflowResult) -> None:
        if result.run_id in self._items:
            raise ValueError(f"run_id already exists: {result.run_id}")
        if result.idempotency_key and result.idempotency_key in self._idempotency:
            raise ValueError("idempotency key already exists")
        self._items[result.run_id] = deepcopy(result)
        if result.idempotency_key:
            self._idempotency[result.idempotency_key] = result.run_id

    def get(self, run_id: str) -> WorkflowResult | None:
        value = self._items.get(run_id)
        return deepcopy(value) if value else None

    def save(self, result: WorkflowResult) -> None:
        self._items[result.run_id] = deepcopy(result)
        if result.idempotency_key:
            self._idempotency[result.idempotency_key] = result.run_id

    def exists(self, run_id: str) -> bool:
        return run_id in self._items

    def find_by_idempotency_key(self, key: str) -> WorkflowResult | None:
        run_id = self._idempotency.get(key)
        return self.get(run_id) if run_id else None


class MemoryAuditStore:
    def __init__(self) -> None:
        self._events: dict[str, list[AuditEvent]] = {}

    def append(self, event: AuditEvent) -> AuditEvent:
        self._events.setdefault(event.run_id, []).append(deepcopy(event))
        return event

    def list_events(self, run_id: str) -> list[AuditEvent]:
        return deepcopy(self._events.get(run_id, []))
