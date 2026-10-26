from fastapi.testclient import TestClient

from decisionflow.api import create_app
from decisionflow.models import ExecutionMode, RunRequest


def test_async_run_endpoint_returns_accepted_and_is_readable(flow, ticket):
    client = TestClient(create_app(flow))
    response = client.post(
        "/v1/runs",
        json=RunRequest(ticket=ticket, execution_mode=ExecutionMode.DETERMINISTIC).model_dump(mode="json"),
    )
    assert response.status_code == 202
    accepted = response.json()
    result = client.get(f"/v1/runs/{accepted['run_id']}")
    assert result.status_code == 200
    assert result.json()["decision"] is not None
    assert client.get(f"/v1/runs/{accepted['run_id']}/events").status_code == 200
