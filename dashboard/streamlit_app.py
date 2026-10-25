from pathlib import Path
import json
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from decisionflow.data import load_jsonl  # noqa: E402
from decisionflow.models import ReviewRecord, ReviewerAction, Ticket  # noqa: E402
from decisionflow.workflow import DecisionFlowWorkflow  # noqa: E402


st.set_page_config(page_title="DecisionFlow Mini", layout="wide")
st.title("DecisionFlow Mini")
st.caption("Governed, evidence-bound workflow — local mock mode")

data_root = ROOT / "data" / "public"
tickets = load_jsonl(data_root / "tickets.jsonl")
selected_id = st.selectbox("Ticket", [row["task_id"] for row in tickets])

if "flow" not in st.session_state:
    st.session_state.flow = DecisionFlowWorkflow(data_root, audit_path=ROOT / "runtime" / "decisionflow.db")
if st.button("Run workflow", type="primary"):
    row = next(item for item in tickets if item["task_id"] == selected_id)
    st.session_state.result = st.session_state.flow.run(Ticket.model_validate(row))

result = st.session_state.get("result")
if result:
    st.subheader(f"Status: {result.status.value}")
    tabs = st.tabs(["Input", "Evidence", "Findings", "Decision", "Draft", "Audit"])
    with tabs[0]:
        st.json(result.ticket.model_dump(mode="json"))
    with tabs[1]:
        st.json([item.model_dump(mode="json") for item in result.evidence])
    with tabs[2]:
        st.json([item.model_dump(mode="json") for item in result.findings])
    with tabs[3]:
        st.json(result.decision.model_dump(mode="json") if result.decision else {})
    with tabs[4]:
        st.write(result.draft_response.message if result.draft_response else "")
    with tabs[5]:
        st.json([item.model_dump(mode="json") for item in result.audit_events])

    if result.status.value == "human_review_required":
        st.divider()
        action = st.selectbox("Reviewer action", [item.value for item in ReviewerAction])
        rationale = st.text_area("Rationale")
        revised = st.text_area("Revised response (required for request_revision)")
        if st.button("Submit review"):
            review = ReviewRecord(
                action=ReviewerAction(action),
                reviewer_id="local-reviewer",
                rationale=rationale,
                revised_response=revised or None,
            )
            st.session_state.result = st.session_state.flow.review(result.run_id, review)
            st.rerun()
