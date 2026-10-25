# DecisionFlow Mini

DecisionFlow Mini is a small, governed workflow for evidence-bound decisions in financial SaaS support operations. It demonstrates how a ticket can be normalized, investigated across read-only sources, converted into source-backed findings, routed by risk, and finalized without allowing unsupported claims or external side effects.

This is a v0.1 public prototype. It is designed to be understandable and runnable locally, not to be presented as a production decision engine.

## What the demo shows

The workflow follows one explicit path:

```text
Ticket
  -> Intake and normalization
  -> Read-only data adaptation
  -> Multi-source evidence retrieval
  -> Evidence-bound findings
  -> Risk and route decision
  -> Constrained response draft
  -> Deterministic compliance gate
       -> completed
       -> human_review_required
  -> Audit snapshot
```

The interactive browser demo makes the same contract visible. It shows:

- what the ticket contains;
- which source records and fields were read;
- which policy sections were selected;
- what the final conclusion is;
- how the case is routed and processed;
- whether the workflow completes or stops for human review;
- why an apparent approval never executes a refund, sends a message, or changes a source system.

Open [the interactive workflow demo](docs/interactive_demo.html) locally in a browser.

## Quick start

Requirements: Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev --extra dashboard
uv run pytest -q
uv run decisionflow --ticket-id T-001
uv run uvicorn decisionflow.api:app --host 127.0.0.1 --port 8000
```

The API exposes:

- `GET /health`
- `POST /v1/workflows`
- `GET /v1/workflows/{run_id}`
- `POST /v1/workflows/{run_id}/reviews`

For a copy-and-run walkthrough, see [docs/demo_walkthrough.md](docs/demo_walkthrough.md).

## Public data

The release contains two agent-visible synthetic fixtures:

- `data/public`: the compact v0.1 baseline fixture used by the default CLI and API;
- `data/public_v02`: the v0.2 multi-source fixture with source registry, source artifacts, entity links, attachments, and policy references.

Both are synthetic. They are not live company, bank, email, or payment data. The source bundle is a local representation of read-only enterprise source contracts; no external connector is called by the default mock runtime.

The private evaluator, gold labels, expected traces, and pattern catalog are intentionally not included in this repository.

## Evidence and safety contract

Every factual claim is linked through this chain:

```text
source_id + record_id + field_path + provenance_hash
  -> EvidenceItem
  -> Finding(status + evidence_refs)
  -> Decision(risk + route + finding_refs)
  -> ResponseClaim(finding_refs)
  -> AuditEvent(actor + transition + refs)
```

The deterministic compliance gate blocks broken provenance, unsupported claims, and forbidden external-action commitments. High- and critical-risk cases require human review. Human approval only changes the internal workflow state and is recorded in the audit trail.

## Runtime modes

- **Mock mode** is the default and runs without credentials.
- An optional OpenAI-compatible provider boundary exists for advisory text generation or schema planning. It is not automatically enabled by `api:app` and cannot own evidence, routing, compliance, review, or external actions.

## Project structure

```text
src/decisionflow/       Workflow, agents, adapter, models, API, and audit log
data/public/            v0.1 public fixture
data/public_v02/        v0.2 multi-source public fixture
docs/                   Architecture, limitations, walkthrough, and browser demo
tests/                  Deterministic unit and API contract tests
dashboard/              Optional Streamlit view
```

## Verification

The development copy was verified with the local deterministic test suite. The public package is a demo-oriented release and does not claim production accuracy, regulatory compliance, or operational readiness.

## License

Add the project license before publishing to a public repository.
