# Architecture

## Design objective

DecisionFlow Mini prioritizes control, testability, traceability, and explicit failure states over open-ended autonomy. The custom state machine owns control flow. Agents cannot choose which safety checks run or mark their own work complete.

## Components

| Component | Responsibility | May use an LLM? | Authority |
|---|---|---:|---|
| Intake Agent | Normalize a ticket into typed fields | Optional | No external side effects |
| Read-only Data Adapter Agent | Discover public source metadata, build a safe query plan, and normalize source records | Advisory only | Read-only; cannot execute arbitrary queries |
| Evidence Retrieval Agent | Query adapted sources and retrieve policy sections | Optional planner | Read-only |
| Finding Agent | Turn source observations into evidence-bound findings and conflict states | Optional later | Cannot route or act |
| Risk and Routing Agent | Produce a typed decision from verified facts and rules | No | Selects an internal route only |
| Response Drafting Agent | Produce a constrained draft with finding-bound claims | Optional | Cannot send |
| Compliance Gate | Enforce provenance, review, and commitment invariants | No | Can block completion |
| Human Review | Approve, reject, or request revision | Human | Internal approval only |
| Audit Logger | Record state transitions and references | No | Append-only contract |

## State transitions

```text
received
  -> normalized
  -> evidence_retrieved
  -> findings_built
  -> decision_made
  -> draft_generated
       -> failed
       -> human_review_required
            -> approved -> completed
            -> rejected
            -> revision_requested
       -> completed
```

## Evidence and finding contract

The workflow now supports two public contracts. Legacy v0.1 tickets continue to
use their flattened context for backwards-compatible routing. Source-aware v0.2
tickets are read through the adapter layer and never require the workflow to know
the physical source file layout.

```text
public source bundle
  -> DataAdapterAgent (schema discovery + read-only plan)
  -> canonical EvidenceItem objects
  -> FindingAgent
  -> RiskRoutingAgent
```

`DataAdapterAgent` can accept an advisory planner (including an LLM), but the
planner only sees public schema metadata and the ticket. It cannot execute a
query, write data, read evaluator-private labels, or bypass the source registry.
The deterministic runtime executes only source IDs and record locators that are
present in the public bundle. A source envelope's `status` is itself evidence,
so `not_found`, `delayed`, `permission_denied`, `partner_unavailable`, and
`conflicting` are preserved instead of being silently converted into false
absence claims.

Finding derivation is relationship-based. The runtime uses category, source
fields, record status, and cross-source joins; `task_id` is retained for trace
and audit only. Tests rename a migrated ticket, remove a key evidence record,
and reorder evidence before running the finding logic.

An evidence locator contains:

- `source_id`: the logical system of record;
- `record_id`: the source record or reproducible query result;
- `field_path`: the exact field used;
- `observed_at` and `retrieved_at`;
- `provenance_hash`: the source-record provenance hash (legacy in-memory evidence
  may use the canonical field value hash);
- `redacted`: whether the visible representation was redacted.
- `source_status` and `access_scope`: availability and access context returned by
  the source adapter.

A finding must reference at least one locator. The compliance gate resolves every locator back to retrieved evidence and verifies its hash. Supported, contradicted, inferred, and unverified states remain distinct.

Absence is not inferred from an empty narrative. An absence finding must reference a reproducible query-result record, such as `payment_ledger:query:acct_001:$.result_count`.

## Traceability and risk containment

The workflow has two explicit invariants that run through the same single
channel. Traceability answers “which source and field supports this statement?”
Risk containment answers “where is an unsafe continuation stopped?”

| Workflow point | Trace artifact | Deterministic guard | If the guard fails |
|---|---|---|---|
| Ticket intake | `run_id`, `task_id`, normalized request | Schema and minimum-input check | Ask for clarification; do not guess |
| Data adaptation | `AdapterPlan`, source registry, lookup keys | Registered source, read-only capability, bounded query | Block adapter and record unresolved mapping |
| Source retrieval | `source_id`, `record_id`, `field_path`, source status | Only typed, allow-listed reads | Preserve `delayed`, `permission_denied`, `conflicting`, or `not_found` |
| Evidence construction | `EvidenceItem`, timestamps, access scope, provenance hash | Locator must resolve to a retrieved record | Finding cannot be supported |
| Finding construction | `fact_key`, status, derivation method, `evidence_refs` | Every finding must cite evidence | Mark `unverified`/`contradicted` or escalate |
| Risk routing | `finding_refs`, policy refs, risk, route | High/critical risk requires human review | Stop automatic completion |
| Response drafting | Claim text → `finding_refs` | No unsupported claim or external-action commitment | Compliance gate blocks completion |
| Compliance and audit | Gate violations, actor, transition, refs, snapshot | Provenance, review, and state invariants | `failed` terminal state with audit record |

The end-to-end trace is therefore:

```text
source record
  -> EvidenceItem(locator + hash + timestamps)
  -> Finding(fact_key + status + evidence_refs)
  -> Decision(risk + route + finding_refs)
  -> ResponseClaim(finding_refs)
  -> AuditEvent(actor + transition + refs)
```

Risk is cut off at multiple independent points rather than at one final prompt:
the adapter cannot write, unavailable sources cannot become facts, incomplete
evidence cannot become a supported finding, high/critical decisions cannot skip
human review, and the compliance gate rejects broken provenance or forbidden
external-action commitments. Approval changes the internal workflow state only;
it does not execute a refund, grant access, delete data, or send a message.

## Human-review invariant

Every `high` or `critical` decision must set `requires_human_review=true`. The compliance gate rejects a decision that violates this invariant. Approval does not execute the underlying business operation; it only approves the internal response or processing instruction.

## Recovery invariant

Audit events are append-only, while the complete `WorkflowResult` is persisted
as a separate SQLite snapshot. A new workflow process can recover a run waiting
for human review, continue it once, and reject duplicate review submissions.
This separation provides both an audit history and a resumable workflow state.

## Cloud execution boundary

The synchronous `/v1/workflows` route remains for backwards-compatible local
calls. Remote clients should use the asynchronous contract:

```text
POST /v1/runs
  -> RunStore creates a RECEIVED snapshot
  -> JobQueue receives a typed JobEnvelope
  -> worker claims the job
  -> deterministic workflow executes
  -> RunStore saves each transition
  -> GET /v1/runs/{run_id} reads the durable result
```

Local mock mode uses `MemoryRunStore` and `LocalJobQueue`. Local development can
use SQLite snapshots. Azure mode uses the optional Azure Table and Storage
Queue adapters and does not depend on the container filesystem for run state.
Azure Blob is reserved for large artifacts. `Idempotency-Key` (or the body
`idempotency_key`) maps repeated submissions to the same run, and a process-local
rate limiter is enabled by default as a last-resort guard; production deployments
should put Front Door/API Management and Entra ID in front of the app.

The Codex bridge is deliberately kept as a separate localhost-only service.
Its token-gated completion endpoint is not mounted on the externally reachable
API, so a cloud request cannot become an arbitrary local command or filesystem
operation. The bridge executor also allow-lists task types, uses `shell=False`,
and confines work to `CODEX_WORKSPACE_ROOT`.

`GET /health/live` is a liveness probe. `GET /health/ready` validates selected
provider, storage, data-root, and local Codex configuration without returning
secrets. The Container Apps Bicep template in `infra/` provisions the storage,
queue, blob, logging, and app boundary but deliberately leaves registry
credentials, Key Vault references, and identity role assignments to the
operator-controlled deployment process.

## Public/private isolation

The runtime reads only the configured public root. The private pattern catalog,
gold labels, evidence graphs, and source-state labels are not imported by any
workflow module. The evaluation adapter exports candidate decisions, findings,
response claims, and source locators; a separate private evaluator performs
exact deterministic comparisons.

## LLM boundary

Mock mode is the baseline. An OpenAI-compatible text provider is isolated behind a small interface. The provider may later assist intake or wording, but it never owns:

- evidence existence or provenance;
- risk classification invariants;
- human-review requirements;
- external actions;
- workflow completion.

The deployed provider factory supports Mock, Azure OpenAI / Foundry v1,
DeepSeek, OpenAI-compatible, and local bridge boundaries. Provider calls are
metadata-only by default: the adapter planner receives schema metadata plus
redacted ticket shape, while the workflow connectivity advisory receives a
fixed contract. Raw ticket messages, account identifiers, evidence values,
findings, and routing details do not leave the deterministic process.

## Adapter safety and migration path

The adapter is intentionally a read-only facade rather than a free-form code
generator. A future production connector can implement the same contract for
SQL, warehouse, document, API, or file sources. Before activation, an adapter
should pass schema, query-safety, entity-join, required-fact, provenance, and
source-failure contract tests. Unknown or low-confidence semantic mappings must
remain unresolved and trigger human review; they must not be silently inferred.

