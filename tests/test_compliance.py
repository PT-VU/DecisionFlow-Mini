from decisionflow.compliance import ComplianceGate


def test_gate_blocks_tampered_evidence_hash(flow, ticket):
    result = flow.run(ticket)
    result.findings[0].evidence_refs[0].provenance_hash = "tampered"

    gate = ComplianceGate().validate(
        evidence=result.evidence,
        findings=result.findings,
        decision=result.decision,
        draft=result.draft_response,
    )

    assert not gate.passed
    assert any("mismatched hash" in violation for violation in gate.violations)

