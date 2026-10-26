from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from ..models import AuditEvent, WorkflowResult, WorkflowStatus


class AzureTableRunStore:
    """Azure Table Storage adapter loaded only when explicitly configured.

    The optional dependency is intentionally not part of the default mock
    install.  Container Apps can install ``azure-data-tables`` and provide a
    managed-identity URL/connection string at deployment time.
    """

    def __init__(self, account_url: str, table_name: str = "DecisionFlowRuns", credential: Any = None):
        try:
            from azure.data.tables import TableServiceClient
        except ImportError as exc:  # pragma: no cover - exercised in cloud image
            raise RuntimeError("Install azure-data-tables to use Azure Table Storage") from exc
        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        service = TableServiceClient(endpoint=account_url, credential=credential)
        self.table = service.create_table_if_not_exists(table_name=table_name)

    def create(self, result: WorkflowResult) -> None:
        if self.get(result.run_id):
            raise ValueError(f"run_id already exists: {result.run_id}")
        if result.idempotency_key and self.find_by_idempotency_key(result.idempotency_key):
            raise ValueError("idempotency key already exists")
        self.save(result)

    def get(self, run_id: str) -> WorkflowResult | None:
        try:
            entity = self.table.get_entity(partition_key="run", row_key=run_id)
        except Exception as exc:  # azure SDK raises ResourceNotFoundError
            if exc.__class__.__name__ == "ResourceNotFoundError":
                return None
            raise
        return WorkflowResult.model_validate_json(entity["snapshot_json"])

    def save(self, result: WorkflowResult) -> None:
        entity = {
            "PartitionKey": "run",
            "RowKey": result.run_id,
            "status": result.status.value,
            "idempotency_key": result.idempotency_key or "",
            "snapshot_json": result.model_dump_json(),
        }
        self.table.upsert_entity(entity, mode="replace")

    def exists(self, run_id: str) -> bool:
        return self.get(run_id) is not None

    def find_by_idempotency_key(self, key: str) -> WorkflowResult | None:
        escaped = key.replace("'", "''")
        pages = self.table.query_entities(query_filter=f"idempotency_key eq '{escaped}'")
        entity = next(iter(pages), None)
        return WorkflowResult.model_validate_json(entity["snapshot_json"]) if entity else None

    def health_check(self) -> None:
        # A bounded query exercises the data-plane credential without mutating
        # application state.
        next(iter(self.table.query_entities(results_per_page=1)), None)


class AzureTableAuditStore:
    """Append-only audit events in a separate Azure Table."""

    def __init__(self, account_url: str, table_name: str = "DecisionFlowAudit", credential: Any = None):
        try:
            from azure.data.tables import TableServiceClient
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install azure-data-tables to use Azure Table Storage") from exc
        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        service = TableServiceClient(endpoint=account_url, credential=credential)
        self.table = service.create_table_if_not_exists(table_name=table_name)

    def append(self, event) -> Any:
        entity = {
            "PartitionKey": event.run_id,
            "RowKey": event.event_id,
            "timestamp": event.timestamp.isoformat(),
            "event_json": event.model_dump_json(),
        }
        self.table.create_entity(entity)
        return event

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
        return self.append(event)

    def list_events(self, run_id: str) -> list:
        escaped = run_id.replace("'", "''")
        rows = self.table.query_entities(query_filter=f"PartitionKey eq '{escaped}'")
        from ..models import AuditEvent

        events = [AuditEvent.model_validate_json(row["event_json"]) for row in rows]
        return sorted(events, key=lambda event: event.timestamp)

    def events(self, run_id: str) -> list:
        return self.list_events(run_id)

    def save_snapshot(self, result: WorkflowResult) -> None:
        # Workflow state is persisted by AzureTableRunStore. This no-op keeps
        # the workflow's shared audit interface intact.
        del result

    def snapshot(self, run_id: str) -> WorkflowResult | None:
        del run_id
        return None

    def find_snapshot_by_idempotency_key(self, key: str) -> WorkflowResult | None:
        del key
        return None

    def health_check(self) -> None:
        next(iter(self.table.query_entities(results_per_page=1)), None)
