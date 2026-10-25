from fastapi.testclient import TestClient

from decisionflow.api import create_app


def test_health(flow):
    client = TestClient(create_app(flow))
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["mode"] == "mock"


def test_api_runs_workflow(flow, ticket):
    client = TestClient(create_app(flow))
    response = client.post("/v1/workflows", json=ticket.model_dump(mode="json"))

    assert response.status_code == 200
    assert response.json()["gate_result"]["passed"] is True

