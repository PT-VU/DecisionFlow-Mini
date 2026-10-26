from fastapi.testclient import TestClient

from decisionflow.api import create_app
from decisionflow.config import Settings


def test_api_key_and_rate_limit_are_opt_in(flow, ticket):
    client = TestClient(create_app(flow, settings=Settings(api_key="secret", rate_limit_per_minute=1)))
    payload = ticket.model_dump(mode="json")
    assert client.post("/v1/workflows", json=payload).status_code == 401
    assert client.post("/v1/workflows", json=payload, headers={"X-API-Key": "secret"}).status_code == 200
    assert client.post("/v1/workflows", json=payload, headers={"X-API-Key": "secret"}).status_code == 429
