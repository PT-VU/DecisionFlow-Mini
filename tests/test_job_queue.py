from decisionflow.jobs import JobWorker, LocalJobQueue
from decisionflow.jobs.azure_storage_queue import AzureStorageQueue
from decisionflow.models import ExecutionMode, JobEnvelope, WorkflowStatus
import json


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


class FakeMessage:
    def __init__(self, content: str, *, dequeue_count: int = 1):
        self.id = f"message-{dequeue_count}"
        self.pop_receipt = f"receipt-{dequeue_count}"
        self.content = content
        self.dequeue_count = dequeue_count


class FakeQueueClient:
    def __init__(self, messages=None):
        self.messages = list(messages or [])
        self.updated = []
        self.deleted = []
        self.sent = []

    def receive_messages(self, **kwargs):
        return self.messages[:1]

    def update_message(self, message_id, receipt, visibility_timeout):
        self.updated.append((message_id, receipt, visibility_timeout))
        return type("Updated", (), {"pop_receipt": f"updated-{receipt}"})()

    def delete_message(self, message_id, receipt):
        self.deleted.append((message_id, receipt))

    def send_message(self, value):
        self.sent.append(value)


def _fake_azure_queue(message):
    queue = object.__new__(AzureStorageQueue)
    queue.queue = FakeQueueClient([message])
    queue.dead_letter_queue = FakeQueueClient()
    queue.visibility_timeout_seconds = 120
    queue.max_attempts = 3
    queue.retry_delay_seconds = 15
    queue._receipts = {}
    queue._attempts = {}
    return queue


def test_azure_queue_failure_retries_without_losing_error():
    envelope = JobEnvelope(job_id="job-retry", run_id="run-retry", execution_mode=ExecutionMode.DETERMINISTIC)
    queue = _fake_azure_queue(FakeMessage(envelope.model_dump_json(), dequeue_count=1))
    claimed = queue.claim("worker")
    assert claimed and claimed.attempt == 0
    queue.fail("job-retry", "first failure\nwith details")
    assert queue.queue.updated == [("message-1", "receipt-1", 15)]
    assert queue.dead_letter_queue.sent == []


def test_azure_queue_failure_dead_letters_at_max_attempts():
    envelope = JobEnvelope(job_id="job-poison", run_id="run-poison", execution_mode=ExecutionMode.DETERMINISTIC)
    queue = _fake_azure_queue(FakeMessage(envelope.model_dump_json(), dequeue_count=3))
    claimed = queue.claim("worker")
    assert claimed and claimed.attempt == 2
    queue.fail("job-poison", "provider timeout\nsecret-like text")
    assert queue.queue.deleted == [("message-3", "receipt-3")]
    assert len(queue.dead_letter_queue.sent) == 1
    dead = json.loads(queue.dead_letter_queue.sent[0])
    assert dead["job_id"] == "job-poison"
    assert "\n" not in dead["error"]
