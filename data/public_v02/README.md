# Public Bundle (v0.2 Multi-Source Fixture)

This is the agent-visible public bundle for the synthetic multi-source dataset. It exposes queryable enterprise source contracts without pre-writing the business conclusions into tickets.

- A fixed seed generates 50 tickets, 12 accounts, and 9 policies; 10 tickets are migrated multi-source investigation cases and 40 remain baseline cases.
- `source_registry.jsonl` describes registered sources, query boundaries, permissions, sensitivity, freshness, and failure states. It contains no expected actions or gold findings.
- `sources/` stores independent source artifacts by source type. Each record includes status, record timestamp, retrieval timestamp, and a provenance hash.
- `source_tools_manifest.json` describes typed read-only source tools. Runtime code must not use arbitrary file paths as a query interface.
- `entity_links.jsonl`, `attachments/index.jsonl`, and the policy index support cross-system entity matching, attachment links, and policy version/section lookup.
- Patterns, gold labels, evidence graphs, required facts, acceptable evidence sets, validators, and expected traces are not included. Those remain private evaluation assets.

The public tickets retain user claims, account/ticket/reference lookup keys, and source hints. Fields such as `issue`, `dispute_status`, `legal_hold`, and `identity_status` are derived from source retrieval and are not copied into the ticket as conclusions.
