from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic

from fastapi import Header, HTTPException, Request


class RateLimiter:
    """Small process-local guard; use Front Door/API Management for production."""

    def __init__(self, per_minute: int = 120):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = monotonic()
        window = self._hits[key]
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= self.per_minute:
            return False
        window.append(now)
        return True


def require_api_key(configured_key: str | None, x_api_key: str | None, authorization: str | None) -> None:
    """Require an API key only when one is configured.

    This keeps local mock mode frictionless while allowing Container Apps to
    put a simple shared key in front of the demo API until Entra ID is added.
    """
    if not configured_key:
        return
    candidate = x_api_key
    if not candidate and authorization and authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
    if candidate != configured_key:
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Valid API key required"})


async def authenticated_request(
    request: Request,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> Request:
    configured = getattr(request.app.state, "settings", None)
    require_api_key(getattr(configured, "api_key", None), x_api_key, authorization)
    limiter = getattr(request.app.state, "rate_limiter", None)
    client_key = request.client.host if request.client else "unknown"
    if limiter is not None and not limiter.allow(client_key):
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Rate limit exceeded"})
    return request

