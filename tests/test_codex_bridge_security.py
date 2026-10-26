from pathlib import Path
import json
import urllib.request

import pytest
from fastapi.testclient import TestClient

from decisionflow.bridge_protocol import BridgeJobRequest
from decisionflow.providers.codex_bridge import CodexBridgeProvider
from local_bridge.bridge_server import create_bridge_app
from local_bridge.security import ensure_allowed_task, resolve_workspace


def test_bridge_rejects_arbitrary_task_type():
    with pytest.raises(ValueError):
        ensure_allowed_task("run_shell_command")


def test_bridge_rejects_workspace_escape(tmp_path):
    with pytest.raises(ValueError):
        resolve_workspace(tmp_path, "..")


def test_bridge_request_contract_accepts_provider_shape():
    request = BridgeJobRequest.model_validate(
        {
            "job_id": "job-1",
            "run_id": "run-1",
            "task_type": "text_completion",
            "prompt": {"system": "system", "user": "user"},
            "workspace_ref": ".",
        }
    )
    assert request.prompt.user == "user"


def test_bridge_server_rejects_missing_token(monkeypatch, tmp_path):
    monkeypatch.setenv("DECISIONFLOW_BRIDGE_TOKEN", "bridge-secret")
    monkeypatch.setenv("CODEX_WORKSPACE_ROOT", str(tmp_path))
    client = TestClient(create_bridge_app())
    payload = {
        "job_id": "job-1",
        "run_id": "run-1",
        "task_type": "text_completion",
        "prompt": {"system": "system", "user": "user"},
        "workspace_ref": ".",
    }
    response = client.post("/internal/bridge/complete", json=payload)
    assert response.status_code == 401


def test_provider_serializes_same_contract_and_reads_structured_result(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"job_id": "job", "status": "completed", "output": "ok"}).encode()

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    output = CodexBridgeProvider("http://bridge", "secret").complete(system="system", user="user")
    body = json.loads(captured["request"].data)
    parsed = BridgeJobRequest.model_validate(body)
    assert parsed.task_type == "text_completion"
    assert parsed.prompt.system == "system"
    assert parsed.prompt.user == "user"
    assert output == "ok"
