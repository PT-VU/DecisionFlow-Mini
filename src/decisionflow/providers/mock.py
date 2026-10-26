from __future__ import annotations

from dataclasses import dataclass

from .base import parse_json_response


@dataclass(frozen=True)
class MockProvider:
    fixture: str = "{\"status\": \"ok\", \"source\": \"mock\"}"

    def complete(self, *, system: str, user: str) -> str:
        del system, user
        return self.fixture

    def complete_json(self, *, system: str, user: str) -> dict:
        return parse_json_response(self.complete(system=system, user=user))
