from __future__ import annotations

import subprocess
from pathlib import Path

from decisionflow.bridge_protocol import BridgeJobRequest, CodexExecutionResult

from .security import ensure_allowed_task, redact_output, resolve_workspace


class CodexExecutor:
    """Execute only predefined local development tasks in a fenced workspace."""

    def __init__(self, workspace_root: Path, codex_command: str = "codex", timeout_seconds: int = 120):
        self.workspace_root = workspace_root.resolve()
        self.codex_command = codex_command
        self.timeout_seconds = timeout_seconds

    def execute(self, job: BridgeJobRequest) -> CodexExecutionResult:
        try:
            ensure_allowed_task(job.task_type)
            workspace = resolve_workspace(self.workspace_root, job.workspace_ref)
            prompt = f"System instructions:\n{job.prompt.system}\n\nUser request:\n{job.prompt.user}"
            if job.task_type == "text_completion":
                args = [self.codex_command, "exec", "--ephemeral", prompt]
            elif job.task_type == "inspect_project":
                args = [self.codex_command, "exec", "--ephemeral", "Inspect the project and summarize files safely."]
            else:
                args = [self.codex_command, "exec", "--ephemeral", "Run the repository's existing tests and report results."]
            completed = subprocess.run(
                args,
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
            )
            output = redact_output(completed.stdout or completed.stderr)
            return CodexExecutionResult(
                job_id=job.job_id,
                status="completed" if completed.returncode == 0 else "failed",
                output=output,
                error=None if completed.returncode == 0 else f"exit_code={completed.returncode}",
            )
        except subprocess.TimeoutExpired:
            return CodexExecutionResult(job_id=job.job_id, status="timeout", error="execution timed out")
        except Exception as exc:
            return CodexExecutionResult(job_id=job.job_id, status="rejected", error=str(exc))
