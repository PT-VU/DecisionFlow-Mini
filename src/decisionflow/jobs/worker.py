from __future__ import annotations

import logging
from threading import Event, Thread
from time import sleep
from uuid import uuid4

from ..models import ExecutionMode, WorkflowStatus
from ..workflow import DecisionFlowWorkflow
from .queue import JobQueue

logger = logging.getLogger("decisionflow.worker")


class JobWorker:
    def __init__(self, queue: JobQueue, workflow: DecisionFlowWorkflow, worker_id: str | None = None):
        self.queue = queue
        self.workflow = workflow
        self.worker_id = worker_id or f"worker-{uuid4()}"

    def process_one(self) -> bool:
        job = self.queue.claim(self.worker_id)
        if job is None:
            return False
        logger.info(
            "job_claimed",
            extra={"job_id": job.job_id, "run_id": job.run_id, "execution_mode": job.execution_mode.value},
        )
        try:
            pending = self.workflow.get(job.run_id)
            stop_heartbeat = Event()
            heartbeat = getattr(self.queue, "heartbeat", None)
            heartbeat_thread = None
            if heartbeat is not None:
                interval = max(1.0, float(getattr(self.queue, "visibility_timeout_seconds", 120)) / 3)

                def heartbeat_loop() -> None:
                    while not stop_heartbeat.wait(interval):
                        heartbeat(job.job_id)

                heartbeat_thread = Thread(target=heartbeat_loop, name=f"heartbeat-{job.job_id}", daemon=True)
                heartbeat_thread.start()
            result = self.workflow.run(
                pending.ticket,
                execution_mode=job.execution_mode,
                dataset_ref=pending.dataset_ref,
                idempotency_key=pending.idempotency_key,
                run_id=job.run_id,
                job_id=job.job_id,
                skip_idempotency=True,
            )
            self.queue.complete(job.job_id, result)
            logger.info(
                "job_completed",
                extra={"job_id": job.job_id, "run_id": job.run_id, "execution_mode": job.execution_mode.value},
            )
        except Exception as exc:
            try:
                failed = self.workflow.get(job.run_id)
                failed.status = WorkflowStatus.FAILED
                failed.error = f"{type(exc).__name__}: {exc}"
                self.workflow.run_store.save(failed)
                self.workflow.audit.save_snapshot(failed)
            except Exception:
                # Preserve the original queue failure; a store outage must not
                # hide the worker exception.
                pass
            self.queue.fail(job.job_id, f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if "stop_heartbeat" in locals():
                stop_heartbeat.set()
            if "heartbeat_thread" in locals() and heartbeat_thread is not None:
                heartbeat_thread.join(timeout=2)
        return True

    def run_forever(self, *, stop_event: Event, poll_seconds: float = 2.0) -> None:
        """Claim until shutdown; SIGTERM handlers set ``stop_event`` in main."""
        while not stop_event.is_set():
            try:
                processed = self.process_one()
            except Exception:
                # The queue implementation owns retry/dead-letter behavior.
                processed = False
            if not processed:
                stop_event.wait(poll_seconds)

