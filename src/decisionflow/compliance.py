from __future__ import annotations

from .models import Decision, DraftResponse, EvidenceItem, Finding, FindingStatus, GateResult, RiskLevel
from .provenance import canonical_hash


class ComplianceGate:
    """Deterministic invariants that an LLM is never allowed to override."""

    def validate(
        self,
        *,
        evidence: list[EvidenceItem],
        findings: list[Finding],
        decision: Decision,
        draft: DraftResponse,
    ) -> GateResult:
        violations: list[str] = []
        evidence_keys = {item.locator.key: item for item in evidence}
        finding_map = {finding.finding_id: finding for finding in findings}

        for item in evidence:
            if item.provenance_scope == "value" and canonical_hash(item.value) != item.locator.provenance_hash:
                violations.append(f"{item.evidence_id} payload does not match its provenance hash")

        for finding in findings:
            for locator in finding.evidence_refs:
                item = evidence_keys.get(locator.key)
                if item is None:
                    violations.append(f"{finding.finding_id} references missing evidence {locator.key}")
                elif item.locator.provenance_hash != locator.provenance_hash:
                    violations.append(f"{finding.finding_id} references evidence with a mismatched hash")

        for finding_id in decision.finding_refs:
            if finding_id not in finding_map:
                violations.append(f"decision references missing finding {finding_id}")

        for claim in draft.claims:
            for finding_id in claim.finding_refs:
                if finding_id not in finding_map:
                    violations.append(f"response claim references missing finding {finding_id}")
            if not claim.finding_refs:
                violations.append("response contains an unbound factual claim")

        if decision.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL} and not decision.requires_human_review:
            violations.append("high-risk decision bypasses human review")
        if draft.commitments:
            violations.append("Phase 1 responses may not contain external-action commitments")
        if any(
            finding.status == FindingStatus.UNVERIFIED and not finding.requires_human_verification
            for finding in findings
        ):
            violations.append("unverified finding lacks human-verification flag")
        return GateResult(passed=not violations, violations=violations)

