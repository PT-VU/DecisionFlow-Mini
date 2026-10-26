from __future__ import annotations

from .config import Settings
from .providers import (
    AzureOpenAIProvider,
    CodexBridgeProvider,
    DeepSeekProvider,
    MockProvider,
    OpenAICompatibleProvider,
    TextProvider,
)
from .providers.azure_openai import entra_token_provider


def build_provider(settings: Settings | None = None) -> TextProvider:
    """Build an advisory provider from environment configuration.

    The workflow never calls this factory for routing or compliance. A missing
    cloud credential therefore cannot silently change deterministic behavior.
    """
    settings = settings or Settings.from_env()
    provider = settings.provider.lower()
    if provider == "mock":
        return MockProvider()
    if provider == "azure_openai":
        endpoint = settings.azure_openai_endpoint or settings.llm_base_url or ""
        deployment = settings.azure_openai_deployment or settings.llm_model or ""
        return AzureOpenAIProvider(
            endpoint=endpoint,
            deployment=deployment,
            api_key=settings.llm_api_key,
            api_version=settings.azure_openai_api_version,
            token_provider=entra_token_provider() if settings.azure_openai_entra else None,
            timeout_seconds=settings.request_timeout_seconds,
        )
    if provider == "deepseek":
        return DeepSeekProvider(
            base_url=settings.llm_base_url or "",
            api_key=settings.llm_api_key or "",
            model=settings.llm_model or "",
            timeout_seconds=settings.request_timeout_seconds,
        )
    if provider == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=settings.llm_base_url or "",
            api_key=settings.llm_api_key or "",
            model=settings.llm_model or "",
            timeout_seconds=settings.request_timeout_seconds,
        )
    if provider == "codex_bridge":
        return CodexBridgeProvider(
            base_url=settings.llm_base_url or "http://127.0.0.1:8787",
            bridge_token=settings.bridge_token or "",
            timeout_seconds=settings.request_timeout_seconds,
        )
    raise ValueError(f"Unsupported DECISIONFLOW_PROVIDER: {settings.provider}")


__all__ = ["TextProvider", "MockProvider", "OpenAICompatibleProvider", "build_provider"]

