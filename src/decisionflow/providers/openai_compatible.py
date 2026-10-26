from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .base import ProviderError, parse_json_response


@dataclass(frozen=True)
class OpenAICompatibleProvider:
    """Minimal OpenAI-compatible client with bounded retries and no key logging."""

    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 30
    max_retries: int = 2

    def complete(self, *, system: str, user: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.load(response)
                content = payload["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ProviderError("Provider content is not text", category="invalid_schema")
                return content
            except urllib.error.HTTPError as exc:
                last_error = exc
                retryable = exc.code == 429 or exc.code >= 500
                if not retryable or attempt >= self.max_retries:
                    raise ProviderError(f"Provider HTTP error {exc.code}", category="http_error", retryable=retryable) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise ProviderError("Provider request failed", category="network_error", retryable=True) from exc
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError("Provider response schema invalid", category="invalid_schema") from exc
            time.sleep(0.2 * (attempt + 1))
        raise ProviderError("Provider request failed", category="network_error", retryable=True) from last_error

    def complete_json(self, *, system: str, user: str) -> dict:
        return parse_json_response(self.complete(system=system, user=user))
