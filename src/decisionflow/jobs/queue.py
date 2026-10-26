from __future__ import annotations

from typing import Protocol

from ..models import JobEnvelope, WorkflowResult


class JobQueue(Protocol):
    def enqueue(self, job: JobEnvelope) -> None: ...

    def claim(self, worker_id: str) -> JobEnvelope | None: ...

    def complete(self, job_id: str, result: WorkflowResult) -> None: ...

    def fail(self, job_id: str, error: str) -> None: ...

