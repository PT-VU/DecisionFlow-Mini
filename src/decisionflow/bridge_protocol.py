from __future__ import annotations

from pydantic import Field

from .models import StrictModel


class BridgePrompt(StrictModel):
    system: str = Field(min_length=1, max_length=8_000)
    user: str = Field(min_length=1, max_length=20_000)


class BridgeJobRequest(StrictModel):
    job_id: str
    run_id: str
    task_type: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    prompt: BridgePrompt
    workspace_ref: str = "."


class CodexExecutionResult(StrictModel):
    job_id: str
    status: str
    output: str = ""
    changed_files: list[str] = Field(default_factory=list)
    diff_ref: str | None = None
    error: str | None = None
