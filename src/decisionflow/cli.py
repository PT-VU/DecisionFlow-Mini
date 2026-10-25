from __future__ import annotations

import argparse
import json
from pathlib import Path

from .data import load_jsonl
from .models import Ticket
from .workflow import DecisionFlowWorkflow
from .evaluation import export_candidate


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the governed DecisionFlow workflow.")
    parser.add_argument("--ticket-id", default="T-001")
    parser.add_argument("--data-root", type=Path, default=Path("data/public"))
    parser.add_argument("--export-candidate", type=Path)
    args = parser.parse_args()

    if args.export_candidate:
        summary = export_candidate(args.data_root, args.export_candidate)
        print(json.dumps(summary, indent=2))
        return

    rows = load_jsonl(args.data_root / "tickets.jsonl")
    try:
        row = next(item for item in rows if item["task_id"] == args.ticket_id)
    except StopIteration as exc:
        raise SystemExit(f"Unknown ticket id: {args.ticket_id}") from exc
    result = DecisionFlowWorkflow(args.data_root).run(Ticket.model_validate(row))
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

