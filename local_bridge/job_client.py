from __future__ import annotations

import time
import urllib.request


class BridgeJobClient:
    """Polling client placeholder; the bridge always initiates outbound calls."""

    def __init__(self, endpoint: str, token: str, timeout_seconds: int = 30):
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def health(self) -> bool:
        request = urllib.request.Request(
            f"{self.endpoint}/health/live",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return response.status == 200
        except Exception:
            return False

