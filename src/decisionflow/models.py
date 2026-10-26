from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Family(StrEnum):
    BILLING = "billing_refund_dispute"
    ACCESS = "access_permission"
    KYC = "kyc_document"
    PRIVACY = "privacy_sensitive_data"
    AI_COMPLAINT = "ai_answer_complaint"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Action(StrEnum):
    ANSWER_WITH_EVIDENCE = "answer_with_evidence"
    ASK_CLARIFICATION = "ask_clarification"
    COLLECT_EVIDENCE = "collect_evidence"
    ROUTE_BILLING_REVIEW = "route_billing_review"
    ROUTE_ACCESS_REVIEW = "route_access_review"
    ROUTE_KYC_REVIEW = "route_kyc_review"
    ROUTE_PRIVACY_REVIEW = "route_privacy_review"
    ROUTE_AI_INCIDENT_REVIEW = "route_ai_incident_review"
    DENY_AUTOMATIC_ACTION = "deny_automatic_action"


class Route(StrEnum):
    SUPPORT = "support"
    BILLING_OPS = "billing_ops"
    SECURITY_ACCESS = "security_access"
    KYC_COMPLIANCE = "kyc_compliance"
    PRIVACY_DPO = "privacy_dpo"
    AI_GOVERNANCE = "ai_governance"
    HUMAN_REVIEW = "human_review"


class WorkflowStatus(StrEnum):
    RECEIVED = "received"
    NORMALIZED = "normalized"
    EVIDENCE_RETRIEVED = "evidence_retrieved"
    FINDINGS_BUILT = "findings_built"
    DECISION_MADE = "decision_made"
    DRAFT_GENERATED = "draft_generated"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionMode(StrEnum):
    """Execution backend selected for a run.

    Deterministic is the safe default. Provider and bridge modes may enrich a
    run, but they never replace the deterministic routing or compliance gate.
    """

    DETERMINISTIC = "deterministic"
    CLOUD_PROVIDER = "cloud_provider"
    EXTERNAL_PROVIDER = "external_provider"
    LOCAL_CODEX_DEV = "local_codex_dev"


def provider_allowed(mode: ExecutionMode, provider_name: str | None = None) -> bool:
    """Whether a configured provider may make an advisory call for this mode."""
    if mode == ExecutionMode.DETERMINISTIC:
        return False
    if provider_name is None:
        return True
    provider = provider_name.lower()
    if mode == ExecutionMode.CLOUD_PROVIDER:
        return provider in {"mock", "azure_openai", "azureopenai", "azureopenaiprovider"}
    if mode == ExecutionMode.EXTERNAL_PROVIDER:
        return provider in {"mock", "deepseek", "openai_compatible", "openaicompatibleprovider"}
    if mode == ExecutionMode.LOCAL_CODEX_DEV:
        return provider in {"codex_bridge", "codexbridgeprovider"}
    return False


class Requester(StrictModel):
    type: str = "customer"
    role: str = "unknown"
    authenticated: bool = False
    authorization_reference: str | None = None


class Ticket(StrictModel):
    task_id: str = Field(pattern=r"^T-[0-9]{3}$")
    message: str = Field(min_length=1)
    account_id: str | None = None
    channel: str = "unknown"
    created_at: datetime = Field(default_factory=utc_now)
    family: Family | None = None
    requester: Requester = Field(default_factory=Requester)
    attachments: list[str] = Field(default_factory=list)
    public_context: dict[str, Any] = Field(default_factory=dict)
    dataset_version: str | None = None


class NormalizedTicket(StrictModel):
    task_id: str
    message: str
    account_id: str | None
    category: Family
    urgency: str
    requester_role: str
    requester_authenticated: bool
    sensitive_signals: list[str]
    risk_hints: list[str]
    missing_information: list[str]


class EvidenceLocator(StrictModel):
    source_id: str
    record_id: str
    field_path: str
    observed_at: datetime
    retrieved_at: datetime = Field(default_factory=utc_now)
    provenance_hash: str
    redacted: bool = False
    source_status: str = "found"
    access_scope: str | None = None

    @property
    def key(self) -> str:
        return f"{self.source_id}:{self.record_id}:{self.field_path}"


class EvidenceItem(StrictModel):
    evidence_id: str
    locator: EvidenceLocator
    value: Any
    content: str
    evidence_type: str
    source_status: str = "found"
    provenance_scope: str = "value"


class FindingStatus(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNVERIFIED = "unverified"
    INFERRED = "inferred"


class Finding(StrictModel):
    finding_id: str = Field(pattern=r"^F-[0-9]{3}$")
    finding_type: str
    subject: str
    claim: str
    value: Any = None
    status: FindingStatus
    evidence_refs: list[EvidenceLocator] = Field(min_length=1)
    derivation_method: str
    input_finding_refs: list[str] = Field(default_factory=list)
    rule_id: str | None = None
    confidence: str = "medium"
    requires_human_verification: bool = False
    fact_key: str | None = None
    conflict_refs: list[str] = Field(default_factory=list)


class Decision(StrictModel):
    task_id: str
    category: Family
    risk: RiskLevel
    action: Action
    route: Route
    requires_clarification: bool
    requires_human_review: bool
    finding_refs: list[str] = Field(min_length=1)
    policy_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    response_constraints: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)


class ResponseClaim(StrictModel):
    text: str = Field(min_length=1)
    finding_refs: list[str] = Field(min_length=1)


class DraftResponse(StrictModel):
    task_id: str
    message: str
    claims: list[ResponseClaim] = Field(default_factory=list)
    commitments: list[str] = Field(default_factory=list)


class GateResult(StrictModel):
    passed: bool
    violations: list[str] = Field(default_factory=list)


class ReviewerAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_REVISION = "request_revision"


class ReviewRecord(StrictModel):
    action: ReviewerAction
    reviewer_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    revised_response: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def revision_requires_text(self) -> "ReviewRecord":
        if self.action == ReviewerAction.REQUEST_REVISION and not self.revised_response:
            raise ValueError("request_revision requires revised_response")
        return self


class AuditEvent(StrictModel):
    event_id: str
    run_id: str
    task_id: str
    event_type: str
    from_status: WorkflowStatus | None
    to_status: WorkflowStatus
    actor: str
    timestamp: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
    finding_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class WorkflowResult(StrictModel):
    run_id: str
    status: WorkflowStatus
    ticket: Ticket
    execution_mode: ExecutionMode = ExecutionMode.DETERMINISTIC
    dataset_ref: str = "public:default"
    idempotency_key: str | None = None
    job_id: str | None = None
    provider_name: str = "deterministic"
    provider_latency_ms: float | None = None
    provider_error: str | None = None
    provider_advisory: str | None = None
    normalized_ticket: NormalizedTicket | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    decision: Decision | None = None
    draft_response: DraftResponse | None = None
    gate_result: GateResult | None = None
    review: ReviewRecord | None = None
    audit_events: list[AuditEvent] = Field(default_factory=list)
    final_response: str | None = None
    error: str | None = None


class RunRequest(StrictModel):
    ticket: Ticket
    execution_mode: ExecutionMode = ExecutionMode.DETERMINISTIC
    dataset_ref: str = "public:default"
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class RunAccepted(StrictModel):
    run_id: str
    job_id: str
    status: WorkflowStatus
    execution_mode: ExecutionMode


class JobEnvelope(StrictModel):
    job_id: str
    run_id: str
    execution_mode: ExecutionMode
    payload_ref: str | None = None
    attempt: int = 0
    created_at: datetime = Field(default_factory=utc_now)

