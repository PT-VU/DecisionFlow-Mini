# Azure deployment readiness

This release contains the code and resource boundaries needed to run the API
in Azure Container Apps with synthetic data.

## Implemented

- Typed `ExecutionMode`, `RunRequest`, `RunAccepted`, and `JobEnvelope` models.
- `POST /v1/runs` asynchronous submission with idempotency and durable status reads.
- `GET /health/live` and `GET /health/ready` probes.
- Memory and SQLite run stores; optional Azure Table run/audit stores.
- Local and optional Azure Storage Queue adapters.
- An independent `decisionflow-worker` entrypoint for Azure Queue consumption,
  visibility renewal, bounded retries, and poison-message handling.
- Append-only audit events and per-transition run snapshots.
- Provider factory for Mock, Azure OpenAI, DeepSeek, OpenAI-compatible, and local bridge boundaries.
- Azure OpenAI endpoint/deployment/API-key or Microsoft Entra token handling.
- Optional API key authentication and a process-local rate limiter.
- `.dockerignore`, public-data-only image boundary, CI Docker build check, and Bicep resources.
- A separate localhost-only Codex bridge with workspace and task allow-lists.

## Deliberate deployment controls

The repository does not include an automatically triggered Azure deployment
workflow, registry administrator credentials, API keys, or Key Vault secrets.
The Bicep file provisions the minimum resources but leaves registry access,
Entra ID, Key Vault references, and Storage data-plane roles to the operator.
Add those controls in the target subscription before using non-synthetic data.

The local Codex bridge is not a production execution path. It is bound to a
developer-controlled local endpoint and cannot be reached by exposing the
Container App API.

The model Provider is advisory only. External providers receive a fixed,
redacted connectivity contract by default; they do not receive ticket text,
account identifiers, evidence values, findings, or routing details.

## Smoke test after deployment

```bash
curl -fsS https://YOUR_APP_FQDN/health/ready
curl -fsS -X POST https://YOUR_APP_FQDN/v1/runs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: smoke-001' \
  --data '{"ticket":{"task_id":"T-001","message":"Please check this duplicate capture.","account_id":"acct_001"}}'
```

Poll `GET /v1/runs/{run_id}` until the workflow reaches a terminal or
human-review state.

The Bicep deployment creates a separate Worker Container App. If deploying
manually, the equivalent local image command is:

```bash
uv run decisionflow-worker
```

The worker requires `DECISIONFLOW_QUEUE_BACKEND=azure`, paired Azure Table run
and audit stores, and the Storage account URL/queue URL variables. It renews
message visibility while processing, retries bounded failures, and sends
poison messages to `<queue-name>-poison`.
