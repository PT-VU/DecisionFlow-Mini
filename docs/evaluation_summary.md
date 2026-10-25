# Evaluation Summary

## Scope

The deterministic benchmark contains 50 synthetic support tickets across billing,
access, KYC, privacy, and AI-answer complaints. Ten tickets use the v0.2
multi-source bundle. Private gold labels, patterns, and evidence graphs remain
isolated from the workflow runtime.

## Result

| Check | Result |
|---|---:|
| Candidate records produced | 50 / 50 |
| Gold-label task records passed | 50 / 50 |
| Evaluator failures | 0 |
| Automated tests | 16 / 16 |

The private evaluator checks category, risk, action, route, clarification,
human-review routing, policy references, exact source locators, finding presence,
required fact keys, provenance hashes, source failure modes, minimum source
counts, conflict handling, and forbidden performed actions. It does not use an
LLM judge.

## Interpretation

This result verifies that the read-only adapter and evidence-bound workflow
conform to the current synthetic contracts. The run was repeated after making
finding derivation depend on source values and joins rather than fixed task
numbers. It is not evidence of production accuracy. The adapter currently has
a deterministic offline planner; a future LLM planner may propose mappings,
but it must remain advisory and pass the same contract tests before activation.

The public runtime tests additionally cover task-id invariance, evidence
mutation, missing evidence, evidence-order invariance, persisted workflow
snapshots, restart recovery, and duplicate-review protection.

The traceability contract is checked at runtime by resolving each finding's
locator back to a registered source record and verifying field paths, source
timestamps, retrieval timestamps, and provenance hashes. Risk containment is
checked separately through high/critical human-review routing, forbidden-action
constraints, response-claim bindings, and the deterministic compliance gate.
