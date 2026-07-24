# Governed mutation catalogue

Read the section that matches the requested operation. Use command `--help` for
current syntax and schema details.

## Package targets

Common targets include Experiment binding and status, implementation Change
plans and reviews, chosen route, results gate rows, result blocks, methods
tried, analysis insights, content-addressed documents, and Rules. Package
policy evaluates lifecycle, phase, blocker, operation, and target together.

`abstract` updates the Package-level Abstract / TLDR rendered in the Overview
Hero lead. The value must be one natural-English paragraph of at most 150
words and must not duplicate `problem`, `objective`, or Direction hypothesis.

`experiment-result-schema` accepts only `update` with
`scope_experiment_id` and `resultSchema`. It attaches the validated schema to
one active, confirmed Experiment binding without changing `Experiment.spec`.
The Package must be unblocked and `ACTIVE / CONTEXT_LOADED`; any existing Run
locks the schema. Use one stable idempotency key per Experiment and schema
digest.

Entering `READY_TO_LAUNCH` requires a sound implementation-review Change with
distinct producer and judge identities. When structured Change plans exist,
every code location and verification must also be currently PASS; stale
observations reject the transition. Historical terminal status mutations may
also require verifier and user acknowledgement Decisions. A vNext Package
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

A schema-backed result must include the manifest produced by
`lib.experiments.result_tables`. Ingest verifies the frozen schema digest,
comprehensive source CSV, exact table set and order, row shape, cell status,
units, and all EvidenceRef hashes before accepting `RunResultFinalized`.

## Retry

Use a stable idempotency key. Reusing it with different content or submitting a
stale expected version is a conflict. Retry only after querying current state.
