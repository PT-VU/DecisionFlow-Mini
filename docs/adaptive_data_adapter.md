# Adaptive Data Access Layer

## Purpose

The workflow must reason about enterprise facts without assuming that every
company stores them in the same table or field names. The adaptive data access
layer separates physical data layout from the workflow's canonical evidence
contract.

```text
source registry + public schema metadata
        -> DataAdapterAgent
        -> validated read-only plan
        -> canonical EvidenceItem
        -> finding / routing / compliance workflow
```

The current implementation uses an offline deterministic planner. It is the
safe baseline for a future AI planner: an LLM may propose semantic mappings, but
the runtime never lets it execute arbitrary queries, write to a source, or read
private evaluator data.

## Adapter contract

The adapter discovers source records and preserves the source envelope. Every
canonical evidence item includes:

- `source_id`, `record_id`, and an exact `field_path`;
- `observed_at` and the source's `retrieved_at`;
- the source record's `provenance_hash`;
- `source_status` and `access_scope`;
- the field value and a human-readable content rendering.

The source envelope's status is queryable evidence. A `permission_denied` or
`partner_unavailable` record must not be treated as proof that a business fact
does not exist.

## Discovery and planning

`PublicDataStore.schema_profile()` exposes only public metadata: registered
source type, allowed query shapes, observed field paths, and observed statuses.
`DataAdapterAgent.discover()` combines that profile with ticket lookup hints to
produce an `AdapterPlan`. The plan is restricted to source IDs present in the
registry or source bundle. The optional planner hook is advisory and its source
selection is allowlisted before use.

## Canonical workflow behavior

For a v0.2 ticket, `EvidenceRetrievalAgent` first asks the adapter for source
records. It adds policy sections through the same evidence constructor. The
Finding Agent then derives fact keys such as:

- `same_invoice_has_two_captures`;
- `external_dispute_is_open`;
- `document_digest_conflict`;
- `legal_hold_is_active`;
- `assistant_made_unsupported_refund_promise`.

Each fact key carries the exact locators used to derive it. Risk routing consumes
these fact keys instead of reading flattened issue fields from the ticket.
Legacy v0.1 tickets continue through the compatibility path so existing tests
and integrations do not break.

## Safety requirements for production connectors

Before a generated adapter is activated against a real system, it must pass:

1. connector and schema validation;
2. read-only query and AST validation;
3. row, field, timeout, and scan-budget limits;
4. entity identity and join tests;
5. required-fact and evidence-locator tests;
6. unavailable-source and conflict tests;
7. PII redaction and prompt-injection checks;
8. human approval for unresolved or low-confidence mappings.

The public synthetic bundle is intentionally small, but the contract is ready to
back relational databases, warehouses, document stores, APIs, and files through
separate connector implementations.
