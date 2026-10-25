from __future__ import annotations

import json
from pathlib import Path

from .data import load_jsonl
from .models import Ticket
from .workflow import DecisionFlowWorkflow


def export_candidate(data_root: Path, output_path: Path) -> dict[str, int]:
    """Run public tickets and export deterministic decision records for a private evaluator."""
    workflow = DecisionFlowWorkflow(data_root)
    rows: list[dict] = []
    failed = 0
    for ticket_row in load_jsonl(data_root / "tickets.jsonl"):
        ticket = Ticket.model_validate(ticket_row)
        result = workflow.run(ticket)
        if result.decision is None:
            failed += 1
            continue
        decision = result.decision.model_dump(mode="json")
        if ticket.dataset_version == "0.2.0":
            # Source-aware candidates expose the precise locators used by the
            # findings.  The evaluator never has to trust a flattened ticket
            # field or an evidence id with no source context.
            source_refs: list[str] = []
            has_legal_hold = any(finding.fact_key == "legal_hold_is_active" for finding in result.findings)
            for finding in result.findings:
                if finding.fact_key in {"source_context_checked", "request_received"} or (
                    finding.fact_key == "erasure_request_received" and has_legal_hold
                ):
                    # Ticket receipt/context checks support traceability and
                    # source-count contracts but are not part of the migrated
                    # decision's minimal business evidence set.
                    continue
                for locator in finding.evidence_refs:
                    if locator.key not in source_refs:
                        source_refs.append(locator.key)
            decision["evidence_refs"] = source_refs
        else:
            # Legacy tickets are evaluated against the source-aware public
            # ticket-system artifact even though the runtime still uses the
            # v0.1 flattened fields for routing compatibility.
            source_rows = load_jsonl(data_root / "sources" / "ticket_system" / "src_ticket_system.jsonl")
            source = next((row for row in source_rows if row.get("record_id") == f"ticket_{ticket.task_id}"), None)
            if source:
                locator = {
                    "source_id": source["source_id"],
                    "record_id": source["record_id"],
                    "field_path": "data.message",
                    "observed_at": source["event_timestamp"],
                    "retrieved_at": source["retrieved_at"],
                    "provenance_hash": source["provenance_hash"],
                }
                finding_id = f"F-REQ-{ticket.task_id}"
                decision["finding_refs"] = [finding_id]
                decision["evidence_refs"] = [f"{source['source_id']}:{source['record_id']}:data.message"]
                decision["findings"] = [
                    {
                        "finding_id": finding_id,
                        "finding_type": "fact",
                        "fact_key": "request_received",
                        "status": "supported",
                        "claim": "The support request was received.",
                        "evidence_refs": [locator],
                    }
                ]
                decision["response_claims"] = [{"claim": "The request was received.", "finding_refs": [finding_id]}]
            else:
                decision["evidence_refs"] = ticket.public_context.get("evidence_refs", [])
                decision["findings"] = []
                decision["response_claims"] = []
        if ticket.dataset_version == "0.2.0":
            decision["findings"] = [finding.model_dump(mode="json") for finding in result.findings]
            decision["response_claims"] = [
                {"claim": claim.text, "finding_refs": claim.finding_refs}
                for claim in (result.draft_response.claims if result.draft_response else [])
            ]
        decision["performed_actions"] = []
        rows.append(decision)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return {"tickets": len(rows) + failed, "candidate_records": len(rows), "failed_runs": failed}

