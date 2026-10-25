from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class TextProvider(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


@dataclass(frozen=True)
class MockProvider:
    fixture: str = "Mock provider output"

    def complete(self, *, system: str, user: str) -> str:
        return self.fixture


@dataclass(frozen=True)
class OpenAICompatibleProvider:
    """Optional runtime adapter. It is never used by compliance or routing gates."""

    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 30

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
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.load(response)
        return payload["choices"][0]["message"]["content"]

