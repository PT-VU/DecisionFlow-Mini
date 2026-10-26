from __future__ import annotations

import logging
import os
import time

from ..config import Settings
from ..llm import build_provider
from ..stores.azure_table import AzureTableAuditStore, AzureTableRunStore
from ..workflow import DecisionFlowWorkflow
from .azure_storage_queue import AzureStorageQueue
from .worker import JobWorker


def build_azure_worker() -> JobWorker:
    settings = Settings.from_env()
    errors = settings.validate_readiness()
    if settings.queue_backend != "azure":
        errors.append("DECISIONFLOW_QUEUE_BACKEND must be azure for worker_main")
    if not settings.azure_storage_account_url:
        errors.append("AZURE_STORAGE_ACCOUNT_URL is required for worker_main")
    if errors:
        raise RuntimeError("; ".join(errors))
    run_store = AzureTableRunStore(settings.azure_storage_account_url)
    audit_store = AzureTableAuditStore(settings.azure_storage_account_url)
    flow = DecisionFlowWorkflow(
        settings.data_root,
        run_store=run_store,
        audit_store=audit_store,
        provider=build_provider(settings),
        provider_name=settings.provider,
    )
    queue_url = settings.azure_storage_queue_url or settings.azure_storage_account_url.replace(".table.", ".queue.")
    queue = AzureStorageQueue(
        queue_url,
        settings.azure_queue_name,
        visibility_timeout_seconds=int(os.getenv("DECISIONFLOW_QUEUE_VISIBILITY_SECONDS", "120")),
        max_attempts=int(os.getenv("DECISIONFLOW_QUEUE_MAX_ATTEMPTS", "3")),
        retry_delay_seconds=int(os.getenv("DECISIONFLOW_QUEUE_RETRY_DELAY_SECONDS", "15")),
    )
    return JobWorker(queue, flow, worker_id=os.getenv("DECISIONFLOW_WORKER_ID"))


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    worker = build_azure_worker()
    poll_seconds = float(os.getenv("DECISIONFLOW_WORKER_POLL_SECONDS", "2"))
    while True:
        try:
            if not worker.process_one():
                time.sleep(poll_seconds)
        except Exception:
            logging.exception("workflow job failed; queue retry/dead-letter policy will apply")
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
