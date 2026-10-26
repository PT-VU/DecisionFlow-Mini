from decisionflow.models import Family, ReviewRecord, ReviewerAction, WorkflowStatus
from decisionflow.workflow import DecisionFlowWorkflow


def test_sqlite_store_recovers_review_state(data_root, ticket, tmp_path):
    risky = ticket.model_copy(
        update={
            "task_id": "T-997",
            "family": Family.PRIVACY,
            "message": "Delete personal data.",
            "requester": ticket.requester.model_copy(update={"authenticated": False}),
            "public_context": {"right": "erasure", "identity_status": "unverified"},
        }
    )
    first = DecisionFlowWorkflow(data_root, audit_path=tmp_path / "runs.db")
    pending = first.run(risky)
    assert pending.status == WorkflowStatus.HUMAN_REVIEW_REQUIRED
    restarted = DecisionFlowWorkflow(data_root, audit_path=tmp_path / "runs.db")
    assert restarted.get(pending.run_id).status == WorkflowStatus.HUMAN_REVIEW_REQUIRED
    completed = restarted.review(
        pending.run_id,
        ReviewRecord(action=ReviewerAction.APPROVE, reviewer_id="reviewer", rationale="verified"),
    )
    assert completed.status == WorkflowStatus.COMPLETED
