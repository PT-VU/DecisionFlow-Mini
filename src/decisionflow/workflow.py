from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

from .adapter import AdapterPlanner, DataAdapterAgent, LLMAdapterPlanner
from .agents import EvidenceRetrievalAgent, FindingAgent, IntakeAgent, ResponseDraftingAgent, RiskRoutingAgent
from .audit import AuditLogger
from .compliance import ComplianceGate
from .config import dataset_hash
from .data import PublicDataStore
from .models import ExecutionMode, ReviewRecord, ReviewerAction, Ticket, WorkflowResult, WorkflowStatus
from .providers.base import TextProvider
from .stores.base import RunStore
from .stores.memory import MemoryRunStore
from .stores.sqlite import SQLiteRunStore


class DecisionFlowWorkflow:
    """Explicit orchestration for governed agents; no free-form agent-to-agent chat."""

    def __init__(
        self,
        data_root: Path,
        audit_path: Path | None = None,
        adapter_planner: AdapterPlanner | None = None,
        run_store: RunStore | None = None,
        audit_store: AuditLogger | None = None,
        provider: TextProvider | None = None,
        provider_name: str | None = None,
    ):
        self.data_root = data_root
        store = PublicDataStore(data_root)
        self.provider = provider
        self.provider_name = provider_name or (provider.__class__.__name__ if provider else "deterministic")
        planner = adapter_planner or (LLMAdapterPlanner(provider) if provider else None)
        self.adapter = DataAdapterAgent(store, planner=planner)
        self.intake = IntakeAgent()
        self.retrieval = EvidenceRetrievalAgent(store, adapter=self.adapter)
        self.finding = FindingAgent()
        self.routing = RiskRoutingAgent()
        self.drafting = ResponseDraftingAgent()
        self.compliance = ComplianceGate()
        self.audit = audit_store or AuditLogger(audit_path)
        self.run_store = run_store or (
            SQLiteRunStore(self.audit) if audit_path else MemoryRunStore()
        )
        self.dataset_hash = dataset_hash(data_root)

    def _transition(self, result: WorkflowResult, status: WorkflowStatus, actor: str, payload: dict | None = None) -> None:
        old = result.status
        result.status = status
        transition_payload = {
            "execution_mode": result.execution_mode.value,
            "dataset_ref": result.dataset_ref,
            "dataset_hash": self.dataset_hash,
            "provider_name": result.provider_name,
            "provider_latency_ms": result.provider_latency_ms,
            "provider_error": result.provider_error,
            **(payload or {}),
        }
        self.audit.record(
            run_id=result.run_id,
            task_id=result.ticket.task_id,
            event_type=status.value,
            from_status=old,
            to_status=status,
            actor=actor,
            payload=transition_payload,
            finding_refs=[f.finding_id for f in result.findings],
            evidence_refs=[e.evidence_id for e in result.evidence],
        )
        result.audit_events = self.audit.events(result.run_id)
        self.run_store.save(result)
        self.audit.save_snapshot(result)

    def _run_provider_advisory(self, result: WorkflowResult) -> None:
        """Exercise the configured provider with metadata only.

        Ticket messages, account identifiers, evidence values, findings and
        routing details never leave this process. The provider is advisory and
        cannot influence the deterministic decision or compliance gate.
        """
        if self.provider is None:
            return
        started = time.perf_counter()
        try:
            raw = self.provider.complete(
                system=(
                    "You are a metadata-only advisory component. Return a short "
                    "capability note. Do not request or infer customer data, risk, "
                    "routing, compliance, or external actions."
                ),
                user=(
                    '{"workflow":"decisionflow","contract":"evidence-bound",'
                    '"data_classification":"synthetic_or_redacted",'
                    '"purpose":"provider_connectivity_check"}'
                ),
            )
            result.provider_advisory = raw[:4000] if isinstance(raw, str) else str(raw)[:4000]
        except Exception as exc:
            result.provider_error = f"{type(exc).__name__}: {exc}"
        finally:
            result.provider_latency_ms = round((time.perf_counter() - started) * 1000, 3)

    def run(
        self,
        ticket: Ticket,
        *,
        execution_mode: ExecutionMode = ExecutionMode.DETERMINISTIC,
        dataset_ref: str = "public:default",
        idempotency_key: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        skip_idempotency: bool = False,
    ) -> WorkflowResult:
        if idempotency_key and not skip_idempotency:
            existing = self.run_store.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        run_id = run_id or str(uuid4())
        result = WorkflowResult(
            run_id=run_id,
            status=WorkflowStatus.RECEIVED,
            ticket=ticket,
            execution_mode=execution_mode,
            dataset_ref=dataset_ref,
            idempotency_key=idempotency_key,
            job_id=job_id,
            provider_name=self.provider_name,
        )
        self.audit.record(
            run_id=run_id,
            task_id=ticket.task_id,
            event_type="ticket_received",
            from_status=None,
            to_status=WorkflowStatus.RECEIVED,
            actor="workflow",
            payload={
                "ticket": ticket.model_dump(mode="json"),
                "execution_mode": execution_mode.value,
                "dataset_ref": dataset_ref,
                "dataset_hash": self.dataset_hash,
            },
        )
        result.audit_events = self.audit.events(run_id)
        self.audit.save_snapshot(result)
        try:
            result.normalized_ticket = self.intake.run(ticket)
            self._transition(result, WorkflowStatus.NORMALIZED, "intake_agent")

            result.evidence = self.retrieval.run(ticket, result.normalized_ticket)
            self._transition(result, WorkflowStatus.EVIDENCE_RETRIEVED, "policy_and_source_retrieval_agent")

            result.findings = self.finding.run(ticket, result.normalized_ticket, result.evidence)
            self._transition(result, WorkflowStatus.FINDINGS_BUILT, "finding_agent")

            result.decision = self.routing.run(result.normalized_ticket, result.evidence, result.findings)
            self._transition(result, WorkflowStatus.DECISION_MADE, "risk_and_routing_agent")

            self._run_provider_advisory(result)

            result.draft_response = self.drafting.run(result.decision, result.findings)
            self._transition(result, WorkflowStatus.DRAFT_GENERATED, "response_drafting_agent")

            result.gate_result = self.compliance.validate(
                evidence=result.evidence,
                findings=result.findings,
                decision=result.decision,
                draft=result.draft_response,
            )
            if not result.gate_result.passed:
                result.error = "; ".join(result.gate_result.violations)
                self._transition(result, WorkflowStatus.FAILED, "compliance_gate", {"violations": result.gate_result.violations})
            elif result.decision.requires_human_review:
                self._transition(result, WorkflowStatus.HUMAN_REVIEW_REQUIRED, "compliance_gate")
            else:
                result.final_response = result.draft_response.message
                self._transition(result, WorkflowStatus.COMPLETED, "compliance_gate")
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            self._transition(result, WorkflowStatus.FAILED, "workflow", {"error": result.error})
        self.run_store.save(result)
        self.audit.save_snapshot(result)
        return result

    def review(self, run_id: str, review: ReviewRecord) -> WorkflowResult:
        result = self.get(run_id)
        if result.status != WorkflowStatus.HUMAN_REVIEW_REQUIRED:
            raise ValueError("Only runs waiting for human review can be reviewed")
        result.review = review
        if review.action == ReviewerAction.APPROVE:
            result.final_response = review.revised_response or (result.draft_response.message if result.draft_response else None)
            self._transition(result, WorkflowStatus.APPROVED, review.reviewer_id, {"rationale": review.rationale})
            self._transition(result, WorkflowStatus.COMPLETED, "workflow")
        elif review.action == ReviewerAction.REJECT:
            self._transition(result, WorkflowStatus.REJECTED, review.reviewer_id, {"rationale": review.rationale})
        else:
            result.final_response = review.revised_response
            self._transition(result, WorkflowStatus.REVISION_REQUESTED, review.reviewer_id, {"rationale": review.rationale})
        self.audit.save_snapshot(result)
        self.run_store.save(result)
        return result

    def get(self, run_id: str) -> WorkflowResult:
        snapshot = self.run_store.get(run_id)
        if snapshot is None:
            snapshot = self.audit.snapshot(run_id)
        if snapshot is not None:
            # Events are append-only and are re-read on recovery so callers see
            # the same audit view as a live workflow instance.
            snapshot.audit_events = self.audit.events(run_id)
            return snapshot
        raise KeyError(f"Unknown run_id: {run_id}")
