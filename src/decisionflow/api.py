from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException

from .models import ReviewRecord, Ticket, WorkflowResult
from .workflow import DecisionFlowWorkflow


def default_data_root() -> Path:
    configured = os.getenv("DECISIONFLOW_DATA_ROOT")
    return Path(configured) if configured else Path(__file__).resolve().parents[2] / "data" / "public"


def create_app(workflow: DecisionFlowWorkflow | None = None) -> FastAPI:
    audit_path = Path(os.getenv("DECISIONFLOW_AUDIT_DB", "runtime/decisionflow.db"))
    flow = workflow or DecisionFlowWorkflow(default_data_root(), audit_path=audit_path)
    app = FastAPI(title="DecisionFlow Mini", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "mock"}

    @app.post("/v1/workflows", response_model=WorkflowResult)
    def run_workflow(ticket: Ticket) -> WorkflowResult:
        return flow.run(ticket)

    @app.get("/v1/workflows/{run_id}", response_model=WorkflowResult)
    def get_workflow(run_id: str) -> WorkflowResult:
        try:
            return flow.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/workflows/{run_id}/reviews", response_model=WorkflowResult)
    def review_workflow(run_id: str, review: ReviewRecord) -> WorkflowResult:
        try:
            return flow.review(run_id, review)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


app = create_app()

