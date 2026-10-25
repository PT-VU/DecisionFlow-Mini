from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .adapter import AdapterPlanner, DataAdapterAgent
from .agents import EvidenceRetrievalAgent, FindingAgent, IntakeAgent, ResponseDraftingAgent, RiskRoutingAgent
from .audit import AuditLogger
from .compliance import ComplianceGate
from .data import PublicDataStore
from .models import ReviewRecord, ReviewerAction, Ticket, WorkflowResult, WorkflowStatus


class DecisionFlowWorkflow:
    """Explicit orchestration for governed agents; no free-form agent-to-agent chat."""

    def __init__(
        self,
        data_root: Path,
        audit_path: Path | None = None,
        adapter_planner: AdapterPlanner | None = None,
    ):
        store = PublicDataStore(data_root)
        self.adapter = DataAdapterAgent(store, planner=adapter_planner)
        self.intake = IntakeAgent()
        self.retrieval = EvidenceRetrievalAgent(store, adapter=self.adapter)
        self.finding = FindingAgent()
        self.routing = RiskRoutingAgent()
        self.drafting = ResponseDraftingAgent()
        self.compliance = ComplianceGate()
        self.audit = AuditLogger(audit_path)
        self._runs: dict[str, WorkflowResult] = {}

    def _transition(self, result: WorkflowResult, status: WorkflowStatus, actor: str, payload: dict | None = None) -> None:
        old = result.status
        result.status = status
        self.audit.record(
            run_id=result.run_id,
            task_id=result.ticket.task_id,
            event_type=status.value,
            from_status=old,
            to_status=status,
            actor=actor,
            payload=payload,
            finding_refs=[f.finding_id for f in result.findings],
            evidence_refs=[e.evidence_id for e in result.evidence],
        )
        result.audit_events = self.audit.events(result.run_id)
        self.audit.save_snapshot(result)

    def run(self, ticket: Ticket) -> WorkflowResult:
        run_id = str(uuid4())
        result = WorkflowResult(run_id=run_id, status=WorkflowStatus.RECEIVED, ticket=ticket)
        self.audit.record(
            run_id=run_id,
            task_id=ticket.task_id,
            event_type="ticket_received",
            from_status=None,
            to_status=WorkflowStatus.RECEIVED,
            actor="workflow",
            payload={"ticket": ticket.model_dump(mode="json")},
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
        self._runs[run_id] = result
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
        self._runs[run_id] = result
        return result

    def get(self, run_id: str) -> WorkflowResult:
        if run_id in self._runs:
            return self._runs[run_id]
        snapshot = self.audit.snapshot(run_id)
        if snapshot is not None:
            # Events are append-only and are re-read on recovery so callers see
            # the same audit view as a live workflow instance.
            snapshot.audit_events = self.audit.events(run_id)
            self._runs[run_id] = snapshot
            return snapshot
        raise KeyError(f"Unknown run_id: {run_id}")
