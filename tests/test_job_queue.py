from decisionflow.jobs import JobWorker, LocalJobQueue
from decisionflow.models import ExecutionMode, JobEnvelope, WorkflowStatus


def test_local_queue_worker_completes_job(flow, ticket):
    queue = LocalJobQueue()
    job = JobEnvelope(job_id="job-1", run_id="run-1", execution_mode=ExecutionMode.DETERMINISTIC)
    pending = flow.run(ticket, run_id="run-1", job_id="job-1", skip_idempotency=True)
    assert pending.status == WorkflowStatus.COMPLETED
    # The queue contract is independently testable even when a run was already
    # materialized; a worker still claims and acknowledges exactly one job.
    queue.enqueue(job)
    worker = JobWorker(queue, flow)
    assert worker.process_one() is True
    assert queue.completed("job-1") is not None
