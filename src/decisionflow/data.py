from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class PublicDataStore:
    """Read-only public data access with a source-aware adapter facade.

    The adapter discovers source artifacts at runtime and exposes a small, typed
    query surface to the workflow.  It deliberately never reads evaluator-private
    files and never mutates the source bundle.  The legacy account/payment files
    remain supported so v0.1 tickets continue to run unchanged.
    """

    def __init__(self, root: Path):
        self.root = root
        self.accounts = {row["account_id"]: row for row in load_jsonl(root / "accounts.jsonl")}
        self.payments = load_jsonl(root / "payments.jsonl")
        self.policy_index = load_jsonl(root / "policy_index.jsonl")
        self._policy_by_id = {row["section_id"]: row for row in self.policy_index}
        self.source_registry = {
            row["source_id"]: row for row in load_jsonl(root / "source_registry.jsonl")
        }
        self.source_records: dict[str, list[dict[str, Any]]] = {}
        self._record_index: dict[tuple[str, str], dict[str, Any]] = {}
        self._discover_source_artifacts()

    def _discover_source_artifacts(self) -> None:
        sources_root = self.root / "sources"
        if not sources_root.exists():
            return
        for path in sorted(sources_root.rglob("*.jsonl")):
            for record in load_jsonl(path):
                source_id = record.get("source_id")
                record_id = record.get("record_id")
                if not source_id or not record_id:
                    continue
                self.source_records.setdefault(source_id, []).append(record)
                self._record_index[(source_id, record_id)] = record

    @property
    def has_source_bundle(self) -> bool:
        return bool(self.source_records)

    def schema_profile(self) -> dict[str, Any]:
        """Return a safe schema summary for the read-only adapter planner.

        Only metadata and field paths are returned; gold labels and expected
        decisions are outside the public root and can never be discovered here.
        """
        profile: dict[str, Any] = {}
        for source_id, records in self.source_records.items():
            paths: set[str] = set()
            statuses: set[str] = set()
            for record in records:
                statuses.add(str(record.get("status", "unknown")))
                paths.update(_flatten_paths(record.get("data", {})))
            profile[source_id] = {
                "source_type": self.source_registry.get(source_id, {}).get("source_type"),
                "allowed_queries": self.source_registry.get(source_id, {}).get("allowed_queries", []),
                "field_paths": sorted(paths),
                "statuses": sorted(statuses),
            }
        return profile

    def source_records_for_ticket(self, ticket: dict[str, Any]) -> list[dict[str, Any]]:
        """Query the discovered source bundle using ticket lookup hints.

        This is the deterministic runtime implementation of the adapter contract.
        An optional LLM can propose mappings later, but it cannot bypass this
        read-only query boundary.
        """
        context = ticket.get("public_context", {})
        hints = context.get("source_hints", [])
        lookup_keys = context.get("lookup_keys", {})
        account_id = ticket.get("account_id")
        candidates: list[dict[str, Any]] = []
        source_ids = list(dict.fromkeys([*hints, "src_ticket_system"]))
        for source_id in source_ids:
            for record in self.source_records.get(source_id, []):
                if _record_matches(
                    record,
                    account_id=account_id,
                    lookup_keys=lookup_keys,
                    ticket_message=ticket.get("message"),
                ):
                    candidates.append(record)
        return candidates

    def records_for_source(self, source_id: str) -> list[dict[str, Any]]:
        return list(self.source_records.get(source_id, []))

    def record(self, source_id: str, record_id: str) -> dict[str, Any] | None:
        return self._record_index.get((source_id, record_id))

    def account(self, account_id: str | None) -> dict[str, Any] | None:
        return self.accounts.get(account_id) if account_id else None

    def payments_for_account(self, account_id: str | None) -> list[dict[str, Any]]:
        if not account_id:
            return []
        return [p for p in self.payments if p.get("account_id") == account_id]

    def policy_sections(self, tags: Iterable[str]) -> list[dict[str, Any]]:
        wanted = {tag.lower() for tag in tags}
        ranked: list[tuple[int, dict[str, Any]]] = []
        for section in self.policy_index:
            section_tags = {
                str(tag).lower()
                for key in ("category_tags", "risk_tags")
                for tag in section.get(key, [])
            }
            score = len(wanted & section_tags)
            if score:
                ranked.append((score, section))
        return [row for _, row in sorted(ranked, key=lambda item: (-item[0], item[1]["section_id"]))]

    def policy_sections_by_id(self, section_ids: Iterable[str]) -> list[dict[str, Any]]:
        return [self._policy_by_id[section_id] for section_id in section_ids if section_id in self._policy_by_id]


def _flatten_paths(value: Any, prefix: str = "data") -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}"
            paths.add(child_prefix)
            paths.update(_flatten_paths(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_prefix = f"{prefix}[{index}]"
            paths.add(child_prefix)
            paths.update(_flatten_paths(child, child_prefix))
    return paths


def _flatten_values(value: Any, prefix: str = "data") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}"
            yield child_prefix, child
            yield from _flatten_values(child, child_prefix)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_prefix = f"{prefix}[{index}]"
            yield child_prefix, child
            yield from _flatten_values(child, child_prefix)


def _record_matches(
    record: dict[str, Any], *, account_id: str | None, lookup_keys: dict[str, Any], ticket_message: str | None = None
) -> bool:
    """Match source records from entity keys, not from the ticket identifier.

    Query envelopes may have no business fields (for example a ``not_found``
    partner response), so correlation tokens are derived from lookup values.
    The ticket id remains a trace key and must not select a business record.
    """
    data = record.get("data", {})
    if record.get("source_id") == "src_ticket_system" and ticket_message is not None:
        return data.get("message") == ticket_message
    haystack = " ".join(
        str(value)
        for value in [record.get("record_id"), data, record.get("source_id")]
    ).lower()
    normalized_haystack = re.sub(r"[^a-z0-9]", "", haystack)
    # Prefer an exact semantic lookup against a field with the same name.  A
    # resource id must not accidentally match because it appears in an
    # allowed_roles list, and an account id must not match an unrelated record
    # merely because it is mentioned in free text.
    direct_matches: list[bool] = []
    for key, wanted in lookup_keys.items():
        values = wanted if isinstance(wanted, list) else [wanted]
        if key in data:
            candidate_values = data[key] if isinstance(data[key], list) else [data[key]]
            direct_matches.append(any(candidate in values for candidate in candidate_values))
    if direct_matches:
        return all(direct_matches)
    if account_id and str(account_id).lower() in haystack:
        return True
    for key, wanted in lookup_keys.items():
        values = wanted if isinstance(wanted, list) else [wanted]
        for value in values:
            if value is None:
                continue
            value_text = str(value).lower()
            normalized_value = re.sub(r"[^a-z0-9]", "", value_text)
            if normalized_value and normalized_value in normalized_haystack:
                return True
            for token in re.findall(r"[a-z]+[0-9]+", value_text):
                token = re.sub(r"[^a-z0-9]", "", token)
                if len(token) >= 3 and token in normalized_haystack:
                    return True
    return False

