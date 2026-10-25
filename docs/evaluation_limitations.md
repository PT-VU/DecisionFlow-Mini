# Evaluation Limitations

## What the current result proves

The current synthetic run checks that the workflow can produce typed decisions
whose required findings, source locators, provenance hashes, source statuses,
conflict flags, review routing, and response references satisfy the private
contract. The evaluator is deterministic and does not use an LLM as a judge.

The 50/50 result is therefore a contract-conformance result for this synthetic
bundle. It is not a production accuracy estimate, a reliability guarantee, or
evidence that the system can safely connect to an arbitrary enterprise source
without connector-specific configuration.

## Important boundaries

- The private evaluator, gold labels, evidence graphs, and pattern catalog are
  outside the agent-visible runtime bundle.
- The v0.2 benchmark contains a deliberately designed source registry and
  source envelopes. Real companies will require a connector and a reviewed
  schema mapping for each system of record.
- The deterministic finding rules are intentionally narrow. They demonstrate
  evidence-bound joins and failure states; they are not a general-purpose
  semantic parser.
- The optional LLM provider is not authoritative. It cannot create evidence,
  change risk rules, bypass human review, or mark a workflow complete.
- The current phase does not execute refunds, grant access, delete data, or
  send external messages.

## Robustness checks now covered

The public test suite verifies that:

1. Changing only a ticket id does not change the source-derived decision.
2. Removing a key payment record removes the duplicate-capture finding.
3. Reordering evidence does not change findings.
4. Missing or unavailable sources remain `unverified` rather than becoming
   supported absence claims.
5. A workflow waiting for human review can be recovered after service restart.
6. A duplicate review submission cannot create a second state transition.

The next meaningful evaluation step is connector-level testing against the
same read-only source contract, followed by a separately reported comparison
of mock and constrained-LLM intake or response drafting. Neither should be
reported as production accuracy.
