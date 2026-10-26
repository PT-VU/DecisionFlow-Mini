from __future__ import annotations

from dataclasses import dataclass

from .base import ProviderError, parse_json_response


@dataclass(frozen=True)
class CodexBridgeProvider:
    """HTTP boundary for the local development bridge.

    This adapter is intentionally not enabled by default and only accepts a
    fixed JSON completion contract from a bridge process.
    """

    base_url: str
    bridge_token: str
    timeout_seconds: float = 30

    def complete(self, *, system: str, user: str) -> str:
        import json
        import urllib.error
        import urllib.request

        body = json.dumps({"task_type": "text_completion", "system": system, "user": user}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/internal/bridge/complete",
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self.bridge_token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError("Codex bridge unavailable", category="bridge_unavailable", retryable=True) from exc
        output = payload.get("output") if isinstance(payload, dict) else None
        if not isinstance(output, str):
            raise ProviderError("Codex bridge response missing output", category="invalid_schema")
        return output

    def complete_json(self, *, system: str, user: str) -> dict:
        return parse_json_response(self.complete(system=system, user=user))
