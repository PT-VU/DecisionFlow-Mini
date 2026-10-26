from decisionflow.config import Settings
from decisionflow.llm import build_provider
from decisionflow.providers import MockProvider
from decisionflow.providers.azure_openai import AzureOpenAIProvider
from decisionflow.workflow import DecisionFlowWorkflow


def test_mock_provider_factory_needs_no_secret():
    provider = build_provider(Settings(provider="mock"))
    assert isinstance(provider, MockProvider)
    assert provider.complete_json(system="", user="")["source"] == "mock"


class RecordingProvider:
    def __init__(self):
        self.calls = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return "safe advisory"


def test_provider_is_called_with_metadata_only(data_root, ticket):
    provider = RecordingProvider()
    result = DecisionFlowWorkflow(data_root, provider=provider, provider_name="recording").run(ticket)
    assert result.provider_name == "recording"
    assert result.provider_advisory == "safe advisory"
    assert len(provider.calls) == 1
    assert "account_id" not in provider.calls[0][1]
    assert ticket.message not in provider.calls[0][1]


def test_azure_openai_provider_uses_deployment_endpoint_and_api_key():
    provider = AzureOpenAIProvider(
        endpoint="https://example.openai.azure.com",
        deployment="gpt-4o-mini",
        api_key="secret",
    )
    assert "/openai/deployments/gpt-4o-mini/chat/completions" in provider._url()
    assert "api-version=" in provider._url()
    assert provider._headers()["api-key"] == "secret"


class FailingProvider:
    def complete(self, *, system: str, user: str) -> str:
        raise RuntimeError("provider unavailable")


def test_provider_failure_does_not_override_deterministic_workflow(data_root, ticket):
    result = DecisionFlowWorkflow(data_root, provider=FailingProvider(), provider_name="failing").run(ticket)
    assert result.gate_result and result.gate_result.passed
    assert result.status.value == "completed"
    assert result.provider_error
