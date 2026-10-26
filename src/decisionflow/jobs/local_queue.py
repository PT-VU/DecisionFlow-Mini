from __future__ import annotations

from collections import deque
from threading import Lock

from ..models import JobEnvelope, WorkflowResult


class LocalJobQueue:
    """At-least-once in-process queue used for tests and local development."""

    def __init__(self) -> None:
        self._pending: deque[JobEnvelope] = deque()
        self._inflight: dict[str, JobEnvelope] = {}
        self._completed: dict[str, WorkflowResult] = {}
        self._failed: dict[str, str] = {}
        self._lock = Lock()

    def enqueue(self, job: JobEnvelope) -> None:
        with self._lock:
            if job.job_id in self._inflight or any(item.job_id == job.job_id for item in self._pending):
                return
            self._pending.append(job)

    def claim(self, worker_id: str) -> JobEnvelope | None:
        del worker_id  # reserved for distributed queue parity
        with self._lock:
            if not self._pending:
                return None
            job = self._pending.popleft()
            self._inflight[job.job_id] = job
            return job

    def complete(self, job_id: str, result: WorkflowResult) -> None:
        with self._lock:
            self._inflight.pop(job_id, None)
            self._completed[job_id] = result

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            self._inflight.pop(job_id, None)
            self._failed[job_id] = error

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def completed(self, job_id: str) -> WorkflowResult | None:
        return self._completed.get(job_id)

    def failed(self, job_id: str) -> str | None:
        return self._failed.get(job_id)
