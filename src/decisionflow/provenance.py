from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from .models import EvidenceItem, EvidenceLocator, utc_now


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_evidence(
    *,
    evidence_id: str,
    source_id: str,
    record_id: str,
    field_path: str,
    value: Any,
    content: str,
    evidence_type: str,
    observed_at: datetime,
    source_status: str = "found",
    access_scope: str | None = None,
    retrieved_at: datetime | None = None,
    provenance_hash: str | None = None,
    provenance_scope: str = "value",
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        locator=EvidenceLocator(
            source_id=source_id,
            record_id=record_id,
            field_path=field_path,
            observed_at=observed_at,
            retrieved_at=retrieved_at or utc_now(),
            provenance_hash=provenance_hash or canonical_hash(value),
            source_status=source_status,
            access_scope=access_scope,
        ),
        value=value,
        content=content,
        evidence_type=evidence_type,
        source_status=source_status,
        provenance_scope=provenance_scope,
    )
