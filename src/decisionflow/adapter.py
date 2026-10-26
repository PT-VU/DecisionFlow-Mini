from __future__ import annotations

"""Read-only schema discovery and source adaptation.

The production boundary is intentionally small: this module can inspect public
source metadata and records, but it cannot write to a source or access private
gold labels.  A future LLM planner may propose a mapping, while this module
continues to execute only the validated, deterministic query plan.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Protocol

from .data import PublicDataStore, _flatten_values
from .models import EvidenceItem, NormalizedTicket, Ticket
from .provenance import make_evidence


class AdapterPlanner(Protocol):
    def propose(self, *, schema_profile: dict[str, Any], ticket: dict[str, Any]) -> dict[str, Any]: ...


class LLMAdapterPlanner:
    """Optional advisory planner backed by the existing text-provider boundary.

    The provider receives metadata and lookup hints only.  Its JSON proposal is
    validated by ``DataAdapterAgent`` before any source record is read.
    """

    def __init__(self, provider: Any):
        self.provider = provider

    def propose(self, *, schema_profile: dict[str, Any], ticket: dict[str, Any]) -> dict[str, Any]:
        try:
            raw = self.provider.complete(
                system=(
                    "You are a read-only schema adapter planner. Return JSON only with "
                    "source_ids (array) and optional mapping_notes. Never invent source IDs."
                ),
                user=json.dumps(
                    {"schema_profile": schema_profile, "ticket": ticket},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        except Exception:
            return {}
        try:
            proposal = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
        return proposal if isinstance(proposal, dict) else {}


@dataclass(frozen=True)
class AdapterPlan:
    source_ids: tuple[str, ...]
    lookup_keys: dict[str, Any]
    confidence: dict[str, float]
    unresolved: tuple[str, ...] = ()


class DataAdapterAgent:
    """Discover a source bundle and expose it as canonical evidence.

    The default planner is deterministic and therefore works offline.  The
    optional planner hook is deliberately advisory: its output can describe
    mappings, but it is not allowed to execute queries or bypass source access
    controls.  This makes the component useful with an LLM while keeping the
    workflow reproducible in tests.
    """

    def __init__(self, store: PublicDataStore, planner: AdapterPlanner | None = None):
        self.store = store
        self.planner = planner
        self.last_plan: AdapterPlan | None = None

    def discover(self, ticket: Ticket) -> AdapterPlan:
        context = ticket.public_context
        hints = tuple(dict.fromkeys([*context.get("source_hints", []), "src_ticket_system"]))
        plan = AdapterPlan(
            source_ids=hints,
            lookup_keys=dict(context.get("lookup_keys", {})),
            confidence={source_id: 1.0 if source_id in self.store.source_records else 0.0 for source_id in hints},
            unresolved=tuple(
                f"source_not_registered:{source_id}"
                for source_id in hints
                if source_id not in self.store.source_records and source_id not in self.store.source_registry
            ),
        )
        if self.planner is not None:
            # The planner only sees metadata and the public ticket.  We keep its
            # output advisory until a future contract validator accepts it.
            proposal = self.planner.propose(
                schema_profile=self.store.schema_profile(),
                ticket={
                    "category": ticket.family.value if ticket.family else None,
                    "channel": ticket.channel,
                    "dataset_version": ticket.dataset_version,
                    "has_account_reference": bool(ticket.account_id),
                    "has_attachments": bool(ticket.attachments),
                },
            )
            if isinstance(proposal, dict):
                proposed_sources = proposal.get("source_ids")
                if isinstance(proposed_sources, list):
                    safe_sources = tuple(
                        source_id
                        for source_id in proposed_sources
                        if source_id in self.store.source_records or source_id in self.store.source_registry
                    )
                    if safe_sources:
                        plan = AdapterPlan(
                            source_ids=tuple(dict.fromkeys([*safe_sources, "src_ticket_system"])),
                            lookup_keys=plan.lookup_keys,
                            confidence=plan.confidence,
                            unresolved=plan.unresolved,
                        )
        self.last_plan = plan
        return plan

    def retrieve(self, ticket: Ticket, normalized: NormalizedTicket) -> list[EvidenceItem]:
        if not self.store.has_source_bundle or ticket.dataset_version != "0.2.0":
            return []
        plan = self.discover(ticket)
        records = self.store.source_records_for_ticket(ticket.model_dump(mode="json"))
        evidence: list[EvidenceItem] = []
        counter = 1
        for record in records:
            source_id = str(record["source_id"])
            if source_id not in plan.source_ids:
                continue
            status = str(record.get("status", "found"))
            observed_at = _parse_datetime(record.get("event_timestamp") or record.get("record_timestamp"))
            retrieved_at = _parse_datetime(record.get("retrieved_at"))
            access_scope = record.get("access_scope")
            # The envelope status is itself evidence.  This is essential for
            # delayed, denied, not-found and conflicting source results.
            evidence.append(
                make_evidence(
                    evidence_id=f"E-{counter:03d}",
                    source_id=source_id,
                    record_id=str(record["record_id"]),
                    field_path="status",
                    value=status,
                    content=f"Source status: {status}.",
                    evidence_type="source_status",
                    observed_at=observed_at,
                    source_status=status,
                    access_scope=access_scope,
                    retrieved_at=retrieved_at,
                    provenance_hash=record.get("provenance_hash"),
                    provenance_scope="source_record",
                )
            )
            counter += 1
            for field_path, value in _flatten_values(record.get("data", {})):
                evidence.append(
                    make_evidence(
                        evidence_id=f"E-{counter:03d}",
                        source_id=source_id,
                        record_id=str(record["record_id"]),
                        field_path=field_path,
                        value=value,
                        content=f"{field_path}: {value}",
                        evidence_type="source_record",
                        observed_at=observed_at,
                        source_status=status,
                        access_scope=access_scope,
                        retrieved_at=retrieved_at,
                        provenance_hash=record.get("provenance_hash"),
                        provenance_scope="source_record",
                    )
                )
                counter += 1
        return evidence


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)
