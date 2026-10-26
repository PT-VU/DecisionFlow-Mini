from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException

from decisionflow.bridge_protocol import BridgeJobRequest, CodexExecutionResult

from .codex_executor import CodexExecutor


def create_bridge_app() -> FastAPI:
    token = os.getenv("DECISIONFLOW_BRIDGE_TOKEN")
    workspace = Path(os.getenv("CODEX_WORKSPACE_ROOT", ".")).resolve()
    executor = CodexExecutor(workspace, os.getenv("CODEX_COMMAND", "codex"))
    app = FastAPI(title="DecisionFlow Local Bridge", version="0.1.0")

    def authorize(authorization: str | None) -> None:
        if not token:
            raise HTTPException(status_code=503, detail="Bridge token is not configured")
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Bridge authentication failed")

    @app.get("/health/live")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/internal/bridge/complete", response_model=CodexExecutionResult)
    def complete(job: BridgeJobRequest, authorization: str | None = Header(default=None)) -> CodexExecutionResult:
        authorize(authorization)
        return executor.execute(job)

    return app


app = create_bridge_app()
