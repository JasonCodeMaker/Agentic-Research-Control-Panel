---
name: research-op
description: "Use when a governed research-state query, package mutation, Scope commit, knowledge registration, run reconciliation, or self-evolve transition is required."
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob
context: fork
---

# Research operation gateway

`research-op` is the narrow management-state gateway. It validates one semantic
command and commits its event, participant versions, current state, idempotency
receipt, and one terminal audit outcome in a SQLite transaction.

## Authority

```text
user or owning research skill
  -> semantic command and policy validation
  -> .research/state/research.sqlite3
  -> rebuildable JSONL, current-state, audit, and interface exports
```

Rejected commands change no domain state. Never work around a rejection by
editing SQLite, JSONL, `current.json`, Run records, generated JavaScript, or
HTML. `RESEARCH_ROOT` defaults to `.research`; `--research-root` is its only
override.

## Bounded queries

Use the smallest query that answers the current decision:

```bash
python3 skills/research-op/scripts/research_op.py \
  show package <package-id> --workspace <workspace>

python3 skills/research-op/scripts/research_op.py \
  context <package-id> --workspace <workspace>

python3 skills/research-op/scripts/research_op.py \
  history package/<package-id> --workspace <workspace>

python3 skills/research-op/scripts/research_op.py \
  audit <command-id> --workspace <workspace>
```

Responses carry `source_seq` and `source_hash`. Prefer `context` for agent work,
`show` for one current record, and `history` only for diagnosis or audit. Never
load all of `current.json` or use interface output as context.

`context` returns a hard-bounded compact packet by default and reports every
omitted category. Add `--experiment <id>` to select one execution target. Use
`--full` only to edit the Draft document, freeze Run authority, audit history,
or diagnose a compact-budget rejection.

## Normal semantic transactions

The normal lifecycle uses the shared transaction kernel:

- `PROJECT_COMMIT`: one reviewed Project and one user authorization;
- `DRAFT_MATERIALIZE`: exact Brainstorm provenance plus Draft Package, with no
  formal approval;
- `DRAFT_REVISE`: one complete revised Draft record;
- `SCOPE_BUNDLE_COMMIT`: reviewed Package, Direction, Experiments, and Scope
  Execution Lease under one user authorization;
- `PACKAGE_DECIDE`: evidence-bound terminal Package plus Decision;
- `ANALYSIS_RECORD` and `RULE_PROMOTE`: governed knowledge transitions.

Each participant declares its expected and resulting aggregate version. One
review digest binds the full payload. A mismatch, stale participant, invalid
actor, or duplicate key with different input rejects the whole operation.
High-level commands belong to `research-onboard`, `research-package`, and
`research-analysis`; do not reconstruct their payloads by hand.

## Package mutations

For an existing active Package, the generic shape is:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> --pkg <package-id> \
  --op <insert|update|delete|check> \
  --target <typed-target> \
  --payload '<json-object>' \
  --idempotency-key <stable-key> \
  --expected-version <aggregate-version>
```

The compact vNext policy derives legal targets from Package lifecycle,
execution phase, and blocker. Legacy Packages retain the historical matrix.
The `abstract` target updates the Package-level Abstract / TLDR used by the
Overview Hero lead; it does not update `problem`, `objective`, or Direction
Scope.
Never mutate `Experiment.spec` through a Package command. Intent changes need a
new Scope review. Package identity changes use the dedicated
`research-package` transaction.

Supply a stable idempotency key for retryable commands and an expected version
when acting on a prior read. An identical retry returns the original event. A
stale version or changed input is a conflict, not permission to bypass policy.

## Runs, results, and facts

The experiment harness writes only inside its assigned Run directory.
Management callbacks authorize launch, register the immutable Run, record its
terminal observation, and ingest a verified result. Result ingest checks Run
identity, status, gate, EvidenceRef hashes, and Package policy before changing
management state.

Checkpoint, sentinel, phase-marker, candidate, metric, and terminal files are
observations. They become scientific claims only through the result and
verifier contracts. Reconciliation may restore a missing callback from
immutable Run evidence; it cannot invent a Run or verdict.

## On-demand references

Load only the reference selected by the request:

- [Compatibility Scope](references/compatibility-scope.md): Proposal/Triage,
  independent Scope revisions, imported workspaces, and low-level repair.
- [Mutation catalogue](references/mutation-catalogue.md): typed Package
  targets, registries, Learnings, Rules, acknowledgements, and run
  reconciliation.

Normal Project and Package work does not load compatibility Scope guidance.

## Interface behavior

Management responses mark the interface stale and report the committed source
sequence. They do not render HTML. Dashboard startup or the next static request
compares its marker with state and coalesces any number of commits into one
rebuild. Interface health never authorizes or invalidates a management command.

## Stop conditions

- Missing or invalid managed root: hand off to `research-init`.
- Missing Project: hand off to `research-onboard`.
- Mutation changes ratified research intent: hand off to `research-scope` or
  the Package Scope Bundle flow.
- Rejection rule or stale version: re-query and repair the input; do not patch
  state.
- Missing evidence or ambiguous verdict: record the gap and stop before a
  success or outcome transition.

## Validation

Use the smallest test layer while iterating, then the relevant component suite:

```bash
python3 -m pytest -q -m core
python3 -m pytest -q tests/research-op tests/research_state
```

For release, also run migration, projection, writer-boundary, and full-suite
checks.
