from fastapi.testclient import TestClient

from decisionflow.api import create_app


def test_same_idempotency_key_returns_same_run(flow, ticket):
    client = TestClient(create_app(flow))
    payload = {"ticket": ticket.model_dump(mode="json"), "idempotency_key": "same-ticket"}
    first = client.post("/v1/runs", json=payload)
    second = client.post("/v1/runs", json=payload)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
