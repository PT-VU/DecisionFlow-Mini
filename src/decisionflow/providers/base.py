from __future__ import annotations

import json
from typing import Protocol


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, category: str = "provider_error", retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.retryable = retryable


class TextProvider(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...

    def complete_json(self, *, system: str, user: str) -> dict: ...


def parse_json_response(text: str) -> dict:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError("Provider returned invalid JSON", category="invalid_json") from exc
    if not isinstance(value, dict):
        raise ProviderError("Provider JSON response must be an object", category="invalid_schema")
    return value
