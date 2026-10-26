from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .base import ProviderError, parse_json_response


@dataclass(frozen=True)
class AzureOpenAIProvider:
    """Azure OpenAI / Foundry v1 adapter.

    The v1 endpoint is ``<endpoint>/openai/v1/chat/completions`` and uses the
    deployment name as the model. Legacy deployment endpoints remain supported
    when an API version is supplied. Authentication can use an API key or a
    lazily-created Microsoft Entra token provider; the key is never logged.
    """

    endpoint: str
    deployment: str
    api_key: str | None = None
    api_version: str | None = None
    token_provider: Callable[[], str] | None = None
    timeout_seconds: float = 30
    max_retries: int = 2

    def _url(self) -> str:
        endpoint = self.endpoint.rstrip("/")
        if "/openai/v1" in endpoint:
            return f"{endpoint}/chat/completions"
        url = f"{endpoint}/openai/deployments/{urllib.parse.quote(self.deployment, safe='')}/chat/completions"
        return f"{url}?api-version={urllib.parse.quote(self.api_version or '2024-10-21', safe='')}"

    def _headers(self) -> dict[str, str]:
        if self.token_provider is not None:
            return {"Authorization": f"Bearer {self.token_provider()}", "Content-Type": "application/json"}
        if self.api_key:
            return {"api-key": self.api_key, "Content-Type": "application/json"}
        raise ProviderError("Azure OpenAI credentials are not configured", category="configuration")

    def complete(self, *, system: str, user: str) -> str:
        body = json.dumps(
            {
                "model": self.deployment,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
            }
        ).encode("utf-8")
        request = urllib.request.Request(self._url(), data=body, method="POST", headers=self._headers())
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.load(response)
                content = payload["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ProviderError("Azure OpenAI response content is not text", category="invalid_schema")
                return content
            except urllib.error.HTTPError as exc:
                last_error = exc
                retryable = exc.code == 429 or exc.code >= 500
                if not retryable or attempt >= self.max_retries:
                    raise ProviderError(f"Azure OpenAI HTTP error {exc.code}", category="http_error", retryable=retryable) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise ProviderError("Azure OpenAI request failed", category="network_error", retryable=True) from exc
            time.sleep(0.2 * (attempt + 1))
        raise ProviderError("Azure OpenAI request failed", category="network_error", retryable=True) from last_error

    def complete_json(self, *, system: str, user: str) -> dict:
        return parse_json_response(self.complete(system=system, user=user))


def entra_token_provider() -> Callable[[], str]:
    """Create a lazy token provider so local mock mode has no Azure dependency."""
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    return lambda: credential.get_token("https://cognitiveservices.azure.com/.default").token

