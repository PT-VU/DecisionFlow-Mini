from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_container_build_is_locked_and_non_root():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "uv sync --frozen" in dockerfile
    assert "COPY pyproject.toml uv.lock" in dockerfile
    assert "USER appuser" in dockerfile
    assert "decisionflow.api:app" in dockerfile


def test_compose_does_not_claim_local_queue_is_shared_between_containers():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'profiles: ["azure"]' in compose
    assert "DECISIONFLOW_QUEUE_BACKEND: azure" in compose
    assert "DECISIONFLOW_RUN_STORE: azure_table" in compose
    assert "DECISIONFLOW_AUDIT_STORE: azure_table" in compose
