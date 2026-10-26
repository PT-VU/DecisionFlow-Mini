from decisionflow.models import WorkflowStatus, WorkflowResult
from decisionflow.stores.memory import MemoryRunStore


def test_memory_run_store_persists_and_deduplicates_by_idempotency(ticket):
    store = MemoryRunStore()
    result = WorkflowResult(run_id="run-1", status=WorkflowStatus.RECEIVED, ticket=ticket, idempotency_key="key-1")
    store.create(result)
    assert store.get("run-1").idempotency_key == "key-1"
    assert store.find_by_idempotency_key("key-1").run_id == "run-1"
