from pathlib import Path

from decisionflow.data import load_jsonl
from decisionflow.agents import FindingAgent
from decisionflow.models import Ticket, WorkflowStatus
from decisionflow.workflow import DecisionFlowWorkflow


SYNTHETIC_PUBLIC = Path(__file__).resolve().parents[1] / "data" / "public_v02"


def _ticket(task_id: str) -> Ticket:
    row = next(
        row for row in load_jsonl(SYNTHETIC_PUBLIC / "tickets.jsonl") if row["task_id"] == task_id
    )
    return Ticket.model_validate(row)


def test_adapter_discovers_public_sources_without_private_gold():
    flow = DecisionFlowWorkflow(SYNTHETIC_PUBLIC)
    profile = flow.adapter.store.schema_profile()

    assert "src_payment_ledger" in profile
    assert "src_acquirer_feed" in profile
    assert all("gold" not in source_id for source_id in profile)
    assert flow.adapter.discover(_ticket("T-001")).source_ids[-1] == "src_ticket_system"


def test_source_adapter_preserves_record_provenance_and_failure_state():
    result = DecisionFlowWorkflow(SYNTHETIC_PUBLIC).run(_ticket("T-030"))

    assert result.status == WorkflowStatus.HUMAN_REVIEW_REQUIRED
    locators = {item.locator.key: item for item in result.evidence}
    identity = locators["src_identity_provider:qry_t030_identity:status"]
    assert identity.locator.source_status == "partner_unavailable"
    assert identity.locator.retrieved_at.isoformat().startswith("2026-10-20T09:40:00")
    assert identity.locator.provenance_hash.startswith("sha256:")
    assert any(finding.fact_key == "document_digest_conflict" for finding in result.findings)


def test_migrated_access_case_is_routed_from_source_findings():
    result = DecisionFlowWorkflow(SYNTHETIC_PUBLIC).run(_ticket("T-019"))

    assert result.decision
    assert result.decision.action.value == "deny_automatic_action"
    assert result.decision.route.value == "human_review"
    assert result.decision.requires_human_review is True
    assert {finding.fact_key for finding in result.findings} >= {
        "requester_has_no_admin_role",
        "customer_authorization_cannot_be_verified",
    }


def test_source_findings_are_invariant_to_ticket_id():
    original = _ticket("T-001")
    renamed = original.model_copy(update={"task_id": "T-901"})

    first = DecisionFlowWorkflow(SYNTHETIC_PUBLIC).run(original)
    second = DecisionFlowWorkflow(SYNTHETIC_PUBLIC).run(renamed)

    assert first.decision and second.decision
    assert (first.decision.action, first.decision.risk, first.decision.route) == (
        second.decision.action,
        second.decision.risk,
        second.decision.route,
    )
    assert {finding.fact_key for finding in first.findings} == {finding.fact_key for finding in second.findings}


def test_source_findings_change_when_key_evidence_is_missing():
    ticket = _ticket("T-001")
    result = DecisionFlowWorkflow(SYNTHETIC_PUBLIC).run(ticket)
    assert result.normalized_ticket

    without_second_capture = [
        item for item in result.evidence if item.locator.record_id != "pay_t001_b"
    ]
    findings = FindingAgent().run(ticket, result.normalized_ticket, without_second_capture)

    assert "same_invoice_has_two_captures" not in {finding.fact_key for finding in findings}


def test_source_finding_is_invariant_to_evidence_order():
    ticket = _ticket("T-001")
    result = DecisionFlowWorkflow(SYNTHETIC_PUBLIC).run(ticket)
    assert result.normalized_ticket

    forward = FindingAgent().run(ticket, result.normalized_ticket, result.evidence)
    reverse = FindingAgent().run(ticket, result.normalized_ticket, list(reversed(result.evidence)))

    assert [(finding.fact_key, finding.value) for finding in forward] == [
        (finding.fact_key, finding.value) for finding in reverse
    ]
