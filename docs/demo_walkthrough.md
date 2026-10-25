# DecisionFlow Mini: Minimal API Demo Walkthrough

This walkthrough verifies the smallest end-to-end loop: submit a ticket, read the persisted workflow snapshot, inspect multi-source evidence, and complete human review for a high-risk case. The workflow does not issue refunds, send messages, modify source systems, or perform other external actions.

## 1. Start the API

From the `DecisionFlow-Mini` directory:

```powershell
uv sync --extra dev
$env:DECISIONFLOW_AUDIT_DB = "runtime/demo.db"
uv run uvicorn decisionflow.api:app --host 127.0.0.1 --port 8000
```

In a second terminal, still in the same directory, check the service:

```powershell
curl.exe -sS http://127.0.0.1:8000/health
```

The response should contain `status=ok`.

## 2. Submit a baseline ticket

The following commands read the first public v0.1 ticket and submit it through the API. The returned `run_id` is the handle for later reads and review actions.

```powershell
$ticket = Get-Content data/public/tickets.jsonl |
  Select-Object -First 1 |
  ConvertFrom-Json
$body = $ticket | ConvertTo-Json -Depth 10 -Compress
$run = curl.exe -sS -X POST http://127.0.0.1:8000/v1/workflows `
  -H "Content-Type: application/json" `
  --data-raw $body | ConvertFrom-Json

$run | Select-Object run_id, status | Format-List
```

Lower-risk tickets generally reach `completed`; high-risk tickets stop at
`human_review_required`. The response contains findings, a decision, a constrained draft, and audit events.

## 3. Run the v0.2 multi-source case

The v0.2 source-aware fixture is included in this release at `data/public_v02`.
Point the API at it without changing the workflow code:

```powershell
$v02 = (Resolve-Path "data\public_v02").Path
$env:DECISIONFLOW_DATA_ROOT = $v02
$env:DECISIONFLOW_AUDIT_DB = "runtime/demo-v02.db"
uv run uvicorn decisionflow.api:app --host 127.0.0.1 --port 8000
```

Stop any previous server first. Then submit T-008:

```powershell
$ticket = Get-Content "$v02\tickets.jsonl" |
  Where-Object { $_ -match '"task_id"\s*:\s*"T-008"' } |
  ConvertFrom-Json
$body = $ticket | ConvertTo-Json -Depth 10 -Compress
$run = curl.exe -sS -X POST http://127.0.0.1:8000/v1/workflows `
  -H "Content-Type: application/json" `
  --data-raw $body | ConvertFrom-Json

$run | Select-Object run_id, status | Format-List
```

The expected status is `human_review_required`. The workflow reads, among other fields:

- `src_acquirer_feed:dsp_t008:data.status = open`: the external payment partner reports an open dispute;
- `src_payment_ledger:refund_t008:data.status = not_started`: the normal refund path has not started;
- `src_payment_ledger:pay_t008:data.state = captured`: the original payment was captured.

Inspect representative evidence locators directly from the response:

```powershell
$run.evidence |
  Where-Object {
    $_.locator.source_id -in @("src_acquirer_feed", "src_payment_ledger")
  } |
  Select-Object -First 8 `
    @{n="source";e={$_.locator.source_id}},
    @{n="record";e={$_.locator.record_id}},
    @{n="field";e={$_.locator.field_path}},
    source_status
```

## 4. Read the snapshot and complete review

GET reads the same `run_id` from the SQLite audit/snapshot store; it does not rerun inference:

```powershell
$snapshot = curl.exe -sS `
  "http://127.0.0.1:8000/v1/workflows/$($run.run_id)" |
  ConvertFrom-Json
$snapshot | Select-Object run_id, status | Format-List
```

T-008 is waiting for human review. Submit an explicit review record:

```powershell
$review = @{
  action = "approve"
  reviewer_id = "demo-reviewer"
  rationale = "Evidence is sufficient for the internal response draft."
} | ConvertTo-Json -Compress

$approved = curl.exe -sS -X POST `
  "http://127.0.0.1:8000/v1/workflows/$($run.run_id)/reviews" `
  -H "Content-Type: application/json" `
  --data-raw $review | ConvertFrom-Json
$approved | Select-Object run_id, status, final_response | Format-List
```

The expected transition is:

```text
human_review_required -> completed
```

Approval only approves the internal workflow result. It does not mean that a refund exists or that any message was sent to a customer or bank.

## 5. Verify traceability

The same response exposes the following deterministic chain:

```text
evidence[].locator
  -> findings[].evidence_refs
  -> decision.finding_refs
  -> draft_response.claims[].finding_refs
  -> audit_events[].evidence_refs / finding_refs
```

Every locator contains at least `source_id`, `record_id`, `field_path`, `observed_at`, and `provenance_hash`. A plausible sentence without a source cannot pass the compliance gate.

## 6. Runtime boundaries

- `data/public` is the compact v0.1 fixture; `data/public_v02` is the source-aware v0.2 fixture.
- Private patterns, gold labels, evidence graphs, and evaluators are not shipped and are never read by runtime code.
- The DecisionFlow HTTP API is ready for local demo and integration calls.
- The optional OpenAI-compatible provider can call `/chat/completions`, but it is not automatically enabled by `api:app`; it remains advisory and cannot decide evidence, routing, compliance, review, or external actions.
- Production deployment still requires authentication, rate limiting, secret management, real connectors, orchestration, and reliability monitoring.
