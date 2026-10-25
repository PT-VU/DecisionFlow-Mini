from decisionflow.models import Family, ReviewRecord, ReviewerAction, WorkflowStatus
from decisionflow.workflow import DecisionFlowWorkflow


def test_low_risk_ticket_runs_end_to_end(flow, ticket):
    result = flow.run(ticket)

    assert result.status == WorkflowStatus.COMPLETED
    assert result.gate_result and result.gate_result.passed
    assert result.findings
    assert result.decision
    assert result.draft_response
    assert result.final_response == result.draft_response.message
    assert result.audit_events[-1].to_status == WorkflowStatus.COMPLETED


def test_every_finding_has_resolvable_evidence(flow, ticket):
    result = flow.run(ticket)
    keys = {item.locator.key for item in result.evidence}

    assert all(finding.evidence_refs for finding in result.findings)
    assert all(locator.key in keys for finding in result.findings for locator in finding.evidence_refs)


def test_every_response_claim_is_bound_to_a_finding(flow, ticket):
    result = flow.run(ticket)
    finding_ids = {finding.finding_id for finding in result.findings}

    assert result.draft_response
    assert all(claim.finding_refs for claim in result.draft_response.claims)
    assert all(ref in finding_ids for claim in result.draft_response.claims for ref in claim.finding_refs)


def test_high_risk_ticket_waits_for_human_review(flow, ticket):
    risky = ticket.model_copy(
        update={
            "task_id": "T-999",
            "family": Family.PRIVACY,
            "message": "Delete all personal data immediately.",
            "requester": ticket.requester.model_copy(update={"authenticated": False}),
            "public_context": {"right": "erasure", "identity_status": "unverified"},
        }
    )
    result = flow.run(risky)

    assert result.status == WorkflowStatus.HUMAN_REVIEW_REQUIRED
    assert result.final_response is None
    reviewed = flow.review(
        result.run_id,
        ReviewRecord(action=ReviewerAction.APPROVE, reviewer_id="reviewer-1", rationale="Identity verified."),
    )
    assert reviewed.status == WorkflowStatus.COMPLETED
    assert reviewed.review is not None


def test_phase_one_never_commits_external_side_effects(flow, ticket):
    result = flow.run(ticket)

    assert result.draft_response
    assert result.draft_response.commitments == []
    assert "execute_refund" in result.decision.forbidden_actions


def test_audit_events_persist_to_sqlite(data_root, ticket, tmp_path):
    audit_db = tmp_path / "audit.db"
    result = DecisionFlowWorkflow(data_root, audit_path=audit_db).run(ticket)
    reopened = DecisionFlowWorkflow(data_root, audit_path=audit_db)

    events = reopened.audit.events(result.run_id)
    assert events
    assert events[-1].to_status == WorkflowStatus.COMPLETED


def test_human_review_workflow_recovers_after_restart(data_root, ticket, tmp_path):
    audit_db = tmp_path / "recovery.db"
    risky = ticket.model_copy(
        update={
            "task_id": "T-998",
            "family": Family.PRIVACY,
            "message": "Delete all personal data immediately.",
            "requester": ticket.requester.model_copy(update={"authenticated": False}),
            "public_context": {"right": "erasure", "identity_status": "unverified"},
        }
    )

    first_process = DecisionFlowWorkflow(data_root, audit_path=audit_db)
    pending = first_process.run(risky)
    assert pending.status == WorkflowStatus.HUMAN_REVIEW_REQUIRED

    restarted = DecisionFlowWorkflow(data_root, audit_path=audit_db)
    recovered = restarted.get(pending.run_id)
    assert recovered.status == WorkflowStatus.HUMAN_REVIEW_REQUIRED
    assert recovered.decision == pending.decision
    assert recovered.findings == pending.findings

    completed = restarted.review(
        pending.run_id,
        ReviewRecord(action=ReviewerAction.APPROVE, reviewer_id="reviewer-1", rationale="Approved after verification."),
    )
    assert completed.status == WorkflowStatus.COMPLETED

    try:
        restarted.review(
            pending.run_id,
            ReviewRecord(action=ReviewerAction.APPROVE, reviewer_id="reviewer-1", rationale="Duplicate submission."),
        )
    except ValueError as exc:
        assert "waiting for human review" in str(exc)
    else:
        raise AssertionError("duplicate review must not create a second transition")
