# Governed mutation catalogue

Read the section that matches the requested operation. Use command `--help` for
current syntax and schema details.

## Package targets

Common targets include Experiment binding and status, implementation review,
chosen route, results gate rows, result blocks, methods tried, analysis
insights, content-addressed documents, and Rules. Package policy evaluates
lifecycle, phase, blocker, operation, and target together.

`abstract` updates the Package-level Abstract / TLDR rendered in the Overview
Hero lead. The value must be one natural-English paragraph of at most 150
words and must not duplicate `problem`, `objective`, or Direction hypothesis.

Entering `READY_TO_LAUNCH` requires a sound implementation-review Change with
distinct producer and judge identities. Historical terminal status mutations
may also require verifier and user acknowledgement Decisions. A vNext Package
closes through `research-package commit-outcome` instead.

## Knowledge registry

`registry-add` records Paper, KnowledgeGap, and KnowledgeEdge aggregates. An
edge is accepted only when both typed endpoints already exist. Generated
registry pages are never inputs to the command.

## Learnings and Rules

A Learning needs verified evidence. Promotion requires an admitted Decision
over that Learning. Retirement requires a lifecycle Decision over the exact
Rule version. Universal Rules are write-locked mirrors; the general Rule path
cannot rewrite `origin=selfevolve` records.

## Acknowledgements

Compatibility acknowledgements are immutable Decision records with a typed
acknowledgement kind and target. A free-form `ack` string has no authority. Do
not add acknowledgements to the normal Scope Execution Lease path.

## Run reconciliation

Use `scan-events` to compare management Run state with immutable Run artifacts.
It may restore missing launch or terminal callbacks and ingest a finalized
result after identity and evidence verification. It may not derive a verdict
from log text, checkpoints, or a terminal marker alone.

## Retry

Use a stable idempotency key. Reusing it with different content or submitting a
stale expected version is a conflict. Retry only after querying current state.
