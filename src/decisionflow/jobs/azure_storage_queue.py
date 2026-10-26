from __future__ import annotations

import json
from typing import Any

from ..models import JobEnvelope, WorkflowResult


class AzureStorageQueue:
    """Azure Storage Queue implementation with optional SDK dependency."""

    def __init__(
        self,
        account_url: str,
        queue_name: str,
        credential: Any = None,
        *,
        visibility_timeout_seconds: int = 120,
        max_attempts: int = 3,
        retry_delay_seconds: int = 15,
    ):
        try:
            from azure.storage.queue import QueueClient
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install azure-storage-queue to use Azure Storage Queue") from exc
        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        self.queue = QueueClient(account_url=account_url, queue_name=queue_name, credential=credential)
        self.queue.create_queue()
        self.visibility_timeout_seconds = visibility_timeout_seconds
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.dead_letter_queue = QueueClient(account_url=account_url, queue_name=f"{queue_name}-poison", credential=credential)
        self.dead_letter_queue.create_queue()
        self._receipts: dict[str, tuple[str, str]] = {}
        self._attempts: dict[str, int] = {}

    def enqueue(self, job: JobEnvelope) -> None:
        self.queue.send_message(job.model_dump_json())

    def claim(self, worker_id: str) -> JobEnvelope | None:
        del worker_id
        messages = self.queue.receive_messages(
            messages_per_page=1,
            visibility_timeout=self.visibility_timeout_seconds,
        )
        for message in messages:
            job = JobEnvelope.model_validate_json(message.content)
            attempt = max(0, int(getattr(message, "dequeue_count", 1)) - 1)
            if attempt >= self.max_attempts:
                self.dead_letter_queue.send_message(
                    JobEnvelope.model_validate_json(message.content).model_copy(update={"attempt": attempt}).model_dump_json()
                )
                self.queue.delete_message(message.id, message.pop_receipt)
                continue
            job = job.model_copy(update={"attempt": attempt})
            self._receipts[job.job_id] = (message.id, message.pop_receipt)
            self._attempts[job.job_id] = attempt
            return job
        return None

    def complete(self, job_id: str, result: WorkflowResult) -> None:
        del result
        receipt = self._receipts.pop(job_id, None)
        self._attempts.pop(job_id, None)
        if receipt:
            self.queue.delete_message(receipt[0], receipt[1])

    def fail(self, job_id: str, error: str) -> None:
        safe_error = str(error).replace("\r", " ").replace("\n", " ")[:2000]
        receipt = self._receipts.get(job_id)
        if receipt:
            attempt = self._attempts.get(job_id, 0)
            if attempt + 1 >= self.max_attempts:
                self.dead_letter_queue.send_message(
                    json.dumps({"job_id": job_id, "error": safe_error, "attempt": attempt + 1})
                )
                self.queue.delete_message(receipt[0], receipt[1])
                self._receipts.pop(job_id, None)
                self._attempts.pop(job_id, None)
            else:
                updated = self.queue.update_message(
                    receipt[0], receipt[1], visibility_timeout=self.retry_delay_seconds
                )
                self._receipts[job_id] = (receipt[0], updated.pop_receipt)

    def heartbeat(self, job_id: str) -> None:
        receipt = self._receipts.get(job_id)
        if receipt:
            updated = self.queue.update_message(
                receipt[0], receipt[1], visibility_timeout=self.visibility_timeout_seconds
            )
            self._receipts[job_id] = (receipt[0], updated.pop_receipt)

    def health_check(self) -> None:
        self.queue.get_queue_properties()

