from pathlib import Path
import json
import os
import sys
import urllib.error
import urllib.request

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from decisionflow.data import load_jsonl  # noqa: E402
from decisionflow.models import ReviewerAction  # noqa: E402


st.set_page_config(page_title="DecisionFlow Mini", layout="wide")
st.title("DecisionFlow Mini")
api_url = st.sidebar.text_input("DecisionFlow API", os.getenv("DECISIONFLOW_API_URL", "http://127.0.0.1:8000"))
api_key = st.sidebar.text_input("API key (optional)", os.getenv("DECISIONFLOW_API_KEY", ""), type="password")
st.caption("Governed, evidence-bound workflow — HTTP client")

data_root = ROOT / "data" / "public"
tickets = load_jsonl(data_root / "tickets.jsonl")
selected_id = st.selectbox("Ticket", [row["task_id"] for row in tickets])

def api_call(method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(f"{api_url.rstrip('/')}{path}", data=body, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


if st.button("Run workflow", type="primary"):
    row = next(item for item in tickets if item["task_id"] == selected_id)
    try:
        accepted = api_call("POST", "/v1/runs", {"ticket": row, "dataset_ref": "public:default"})
        st.session_state.run_id = accepted["run_id"]
        st.session_state.accepted = accepted
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        st.error(f"API unavailable: {exc}")

if st.session_state.get("run_id"):
    try:
        st.session_state.result = api_call("GET", f"/v1/runs/{st.session_state.run_id}")
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        st.error(f"Unable to read run: {exc}")

result = st.session_state.get("result")
if result:
    st.subheader(f"Status: {result['status']}")
    tabs = st.tabs(["Input", "Evidence", "Findings", "Decision", "Draft", "Audit"])
    with tabs[0]:
        st.json(result["ticket"])
    with tabs[1]:
        st.json(result["evidence"])
    with tabs[2]:
        st.json(result["findings"])
    with tabs[3]:
        st.json(result.get("decision") or {})
    with tabs[4]:
        st.write((result.get("draft_response") or {}).get("message", ""))
    with tabs[5]:
        st.json(result["audit_events"])

    if result["status"] == "human_review_required":
        st.divider()
        action = st.selectbox("Reviewer action", [item.value for item in ReviewerAction])
        rationale = st.text_area("Rationale")
        revised = st.text_area("Revised response (required for request_revision)")
        if st.button("Submit review"):
            try:
                st.session_state.result = api_call(
                    "POST",
                    f"/v1/runs/{st.session_state.run_id}/reviews",
                    {
                        "action": action,
                        "reviewer_id": "dashboard-reviewer",
                        "rationale": rationale,
                        "revised_response": revised or None,
                    },
                )
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                st.error(f"Review failed: {exc}")
            st.rerun()
