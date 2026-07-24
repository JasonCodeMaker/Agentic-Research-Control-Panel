---
name: research-package
description: "Use when converting a Brainstorm, refining a Draft Package, atomically finalizing Scope, or restructuring a state-backed Package."
---

# Research package

Use this skill for one governed Package. The normal path turns one exact
Brainstorm into a non-executable Draft, refines the plan, commits one complete
Scope Bundle, and later records one evidence-bound outcome.

## Authority and boundaries

`.research/state/research.sqlite3` is management authority. Run evidence lives
under `.research/experiments/`. JSONL, `current.json`, and the entire interface
are exports or projections. Use `research-op` queries and management commands;
never edit those files directly or recover state from HTML.

Scope is `Project -> Direction -> Experiment`. Package is the authoring and
execution container, not another Scope level. A Draft has no execution
authority. An active Package can execute only the Experiments listed by its
open Scope Execution Lease.

## Normal path

```text
coherent Brainstorm
  -> DRAFT_MATERIALIZE by the agent, no formal approval
  -> Draft refinement
  -> one complete Scope Bundle review
  -> one user authorization and one atomic transaction
  -> ACTIVE / CONTEXT_LOADED with an open Execution Lease
  -> Runs and optional analysis
  -> one evidence-bound SUCCESS or FAIL review and authorization
```

Do not create separate Direction and Experiment approvals, a Package
finalization Proposal, or a per-launch acknowledgement on this path.

### 1. Materialize one Brainstorm

Choose a concise title that expresses the Package's research purpose:

```bash
python3 skills/research-package/scripts/draft_package.py \
  --workspace <cwd> convert \
  --brainstorm-id <brainstorm-id> \
  --title <agent-designed-title> \
  --title-rationale "<why this title captures the purpose>" \
  --actor-id <agent-id>
```

`DRAFT_MATERIALIZE` binds the exact Brainstorm version and NoteRef, keeps the
Brainstorm as `MATERIALIZED` provenance, and creates one `DRAFT / REFINING`
Package. It creates no Scope or execution authority. It seeds the complete
standard Package page set, including an empty Analysis page; later evidence may
populate that page without another page-initialization step.

The agent writes `Package.abstract` as the Overview Hero lead. It is one
natural-English paragraph of at most 150 words that summarizes the whole
Package in execution order: what happens first, what follows, and what the
combined work is meant to determine. Detailed controls and gates belong in
Scope and Plan. Do not copy `problem`, `objective`, or the Direction hypothesis
into `abstract`, and do not claim an unmeasured outcome.

### 2. Refine the Draft in two reviewed phases

Request `research-op context <package-id> --full` when editing the proposal;
the default compact packet intentionally omits its HTML body.

```bash
python3 skills/research-package/scripts/draft_package.py \
  --workspace <cwd> revise \
  --package-id <package-id> \
  --patch '<json-object>' \
  --body-file <proposal-fragment.html>
```

Read [Draft refinement pipeline](references/draft-refinement.md) first. It
defines reviewed Overview and Plan, then reviewed Implementation and Results
with derived Tracker and conditional Guide Docs. Each phase uses `grilling`
for 1-5 high-impact questions, then validates and shows the complete phase.
Phase 2 changes to Phase 1 content return to Phase 1 review.

Each change advances `draftRevision` and keeps `draftStatus=REFINING`. Do not
set `SCOPE_READY`, commit Scope, create executable aggregates, edit code,
launch a Run, or bypass a missing Draft writer with an active-only mutation.

### 3. Review and commit the Scope Bundle

Prepare one review containing the complete Direction, every selected
Experiment, and `Package.resourcePolicy` when active Resource presets exist.
The review also shows the exact four-field Research Intent; the Package
Hypothesis must match `Direction.spec.hypothesis`:

```bash
python3 skills/research-package/scripts/draft_package.py \
  --workspace <cwd> review-scope \
  --package-id <package-id> \
  --direction '<complete-direction-node>' \
  --experiments '<complete-experiment-node-array>'
```

Show the semantic content once and keep the receipt internal. After the user
approves that exact bundle:

```bash
python3 skills/research-package/scripts/draft_package.py \
  --workspace <cwd> commit-scope \
  --package-id <package-id> \
  --direction '<same-direction-node>' \
  --experiments '<same-experiment-node-array>' \
  --review-sha256 <internal-digest> \
  --actor-id <stable-user-id> \
  --review-id <conversation-review-id>
```

The transaction fails closed if the Draft revision, document hash, Scope
content, or participant versions changed. An identical retry is idempotent. A
successful commit writes Package, Direction, and Experiments together, keeps
the same Package and proposal document, and opens the bounded Execution Lease.

### 4. Freeze Result schemas

During Draft refinement, decide what the user must compare after each
Experiment. An Experiment may need zero or more Result tables. Omit
`resultSchema` when no table helps the decision; otherwise define only the
decision-relevant rows, metrics, units, and comparison arms. Use `main` for
primary evidence and `ablation` only for a real component or policy ablation.
Do not add a Hypothesis restatement, evaluation-contract banner, package-level
gate ledger, or speculative table.

After activation and before the first Run, write each non-empty schema through
the `experiment-result-schema` research-op target. The gateway accepts this
only for an unblocked `ACTIVE / CONTEXT_LOADED` Package and permanently locks
the schema when the Experiment gets its first Run. Measured values never belong
in the schema.

Read [Results page pattern](references/results-page-pattern.md) for the schema,
CSV extraction, null-state, evidence, and rendering contract.

### 5. Materialize the Implementation map

Before editing code, record one or more state-backed Changes for every
Experiment. Each Change contains:

- a concise `title` and positive integer `order` within its Experiment;
- one or more `validating_experiments`;
- `plan.how_it_changes`;
- `plan.code_locations[]`, each with a stable `id`, relative `path`, and one
  action: `REUSE`, `ADD`, `MODIFY`, `LINK`, or `OUTPUT`; and
- `plan.verifications[]`, each with a stable `id`, human-readable `label`,
  dependencies, and a runnable argument-list `command` when automation is
  possible.

Write Changes through the `tracker-impl-review-row` research-op target. The
gateway freezes the code-location baselines at this point, so materialize the
map before making the corresponding edit. Do not store pseudo-code, a
Hypothesis copy, Plan coverage, criticality chips, test catalogs, checkbox
booleans, or UI prose in the Package.

The generated Implementation page groups Changes by Experiment and displays
only Code locations, How it changes, and Verification. Its disabled checkboxes
are projections of Change observations; browser input is never persisted.
If Package work includes code edits in the same turn, run
`research-run/scripts/implementation_status.py sync` after each logical edit
batch before returning control.

Tracker is not another authored checklist. The Dashboard derives its `To-Do`
from these Changes, the Package Experiments, and Run evidence. Do not create
Tracker rows or checkbox booleans; hand execution to `research-run`, which
updates the owning Change or Run after each completed task.

### 6. Close the Package

Only after relevant Runs are terminal and evidence has been reviewed, prepare
one outcome:

```bash
python3 skills/research-package/scripts/draft_package.py \
  --workspace <cwd> review-outcome \
  --package-id <package-id> \
  --outcome <SUCCESS-or-FAIL> \
  --reason "<evidence-backed conclusion>" \
  --evidence '<evidence-reference-array>' \
  --actor-id <stable-user-id>
```

After the user approves the same content:

```bash
python3 skills/research-package/scripts/draft_package.py \
  --workspace <cwd> commit-outcome \
  --package-id <package-id> \
  --outcome <same-outcome> \
  --reason "<same-conclusion>" \
  --evidence '<same-evidence-reference-array>' \
  --review-sha256 <internal-digest> \
  --actor-id <stable-user-id> \
  --review-id <conversation-review-id>
```

`PACKAGE_DECIDE` writes the terminal Package and Decision together and closes
the lease. SUCCESS becomes `ADOPTED`; FAIL becomes `ARCHIVED`.
`research-analysis` is optional and adds no mandatory approval boundary.

## On-demand references

Read only the reference needed by the request:

- [Draft refinement pipeline](references/draft-refinement.md): two-phase Draft
  authoring and review.
- [Package contract](references/package-contract.md): record fields, evidence,
  result, and projection contracts.
- [Pre-run revision and compatibility](references/compatibility-workflows.md):
  bounded pre-run revision, imported Scope activation, reopen/reactivation,
  identity rename, legacy Brainstorm transfer, and manual creation.
- [Results page pattern](references/results-page-pattern.md): Result schema,
  CSV extraction, evidence, and rendering work.

Do not load compatibility guidance during initial Draft refinement.

## Stop conditions

- No active Project: hand off to `research-onboard`.
- Idea is still changing at the question level: return to `research-brainstorm`.
- Draft or reviewed bundle changed: prepare a new review; never reuse the old
  digest.
- User changes ratified Direction or Experiment intent: use a new Scope review.
- Open Runs exist: do not close, reopen, rename, or archive the Package.
- Evidence is missing or does not support the requested outcome: report the gap
  instead of committing a Decision.

## Validation

Run the checks proportional to the change:

```bash
python3 -m pytest -q -m core
python3 -m pytest -q tests/research-package
python3 -m py_compile skills/research-package/scripts/*.py
```

For a committed Scope Bundle, verify the same event appears in Package,
Direction, and Experiment history; the lease contains exactly the reviewed
Experiment ids; the proposal NoteRef is unchanged; and no normal-path Proposal
aggregate was created. Validate interface rendering separately through
`research-dashboard`.
