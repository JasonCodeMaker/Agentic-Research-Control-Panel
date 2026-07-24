---
name: research-run
description: "Use when the user invokes /research-run or asks to execute, continue, monitor, verify, or finish an existing research package."
allowed-tools: Bash(python3 *), Bash(node *), Read, Edit, Write, Grep, Glob, Agent
---

# research-run

## Purpose

`/research-run` executes an existing Package one Experiment at a time. It starts only after Project,
Direction, Experiment, and Package records exist in management state. If one is missing, the command
returns a handoff to the skill that owns it.

The command keeps running or monitoring until it reaches one of these outcomes:

- the Package has an evidence-backed terminal result;
- a proposal or user decision blocks further work;
- an external dependency has a concrete blocker and a recorded next action.

It never invokes git.

## Authority boundary

Management state lives in `.research/state/events.jsonl`. Run measurements live under
`.research/experiments/`. Files under `.research/interface/` are generated views for people.
`research-run` does not read them, and a missing interface does not block execution.

`research-run` may:

- query the selected Package, Experiment, open Runs, Decisions, Rules, and evidence;
- dispatch implementation, review, launch, monitoring, and verification work;
- launch or inspect a Run through `lib.experiments`;
- emit commands for `research-op`;
- reconcile experiment callbacks with `research-op --op scan-events`.

It may not:

- create or revise Project, Direction, or Experiment intent;
- materialize a Package;
- append management events directly;
- treat generated HTML or JavaScript as state;
- copy a measured value into an Experiment gate.

## Code entry points

| Purpose | Entry point |
| --- | --- |
| Admission | `skills/research-run/scripts/admission.py` |
| Dispatch and command envelopes | `skills/research-run/scripts/driver.py` |
| State queries | `skills/research-op/scripts/research_op.py` |
| Launch | `lib/experiments/launch.py` |
| Monitor | `lib/experiments/report.py` |
| Reconcile callbacks | `lib/experiments/reconcile.py` |
| Result table extraction | `lib/experiments/result_tables.py` |
| Result finalization | `lib/experiments/extract.py` |
| Implementation checkbox sync | `skills/research-run/scripts/implementation_status.py` |
| Workflow routing | `workflow.ts` |

Admission and dispatch resolve the workspace with `ResearchPaths` and read bounded snapshots through
`StateQuery`.

All commands accept a workspace and the same `--research-root` override. The default root is
`.research`.

## Admission

Run admission checks structured state in this order:

| State | Meaning | Handoff |
| --- | --- | --- |
| `NO_PROJECT` | no active Project | `/research-onboard` |
| `NO_DIRECTION` | no active Direction | `/research-brainstorm` |
| `NO_EXPERIMENT` | no Experiment belongs to the active Direction | `/research-scope` |
| `NO_PACKAGE` | no Package materializes the Direction and Experiment | `/research-package from-scope <direction-id>` |
| `NOT_READY` | Package exists but readiness has not passed | run readiness checks |
| `READY` | the selected Experiment can enter the execution loop | continue |

Use:

```python
import sys

sys.path.insert(0, "skills/research-run/scripts")
import admission

state = admission.detect_admission_state(workspace, pkg_id=package_id)
result = admission.run_front_door(
    workspace,
    pkg_id=package_id,
    readiness_ok=True,
    role_sequence=roles,
    adapters=adapters,
)
```

The source directory is not a Python package in every installation, so script callers may import it by
adding `skills/research-run/scripts` to `sys.path`, as the local tests do.

Admission returns `source_seq` and `source_hash`. Keep both on every dispatched role report. A report
from an older state snapshot is rejected.

The interface is deliberately absent from this state machine. Do not add an interface-init handoff to
the run path.

## Procedure

### 1. Read bounded context

Read only the selected Package context:

```bash
python3 skills/research-op/scripts/research_op.py \
  context <package-id> --workspace . --research-root .research
```

For a precise record or history:

```bash
python3 skills/research-op/scripts/research_op.py \
  show experiment '<package-id>::<experiment-id>' \
  --workspace . --research-root .research

python3 skills/research-op/scripts/research_op.py \
  history 'package/<package-id>' \
  --workspace . --research-root .research
```

Context is an in-memory projection. Do not persist a package-level context pack. The launcher freezes
the exact input used by a Run in that Run's `context.json`.

### 2. Select one Experiment

Choose a Package-owned Experiment whose dependencies and status permit execution. Read its `spec`
directly from state. The minimum executable spec contains:

- `purpose`;
- `config_ref`;
- `gate`;
- `control_mode`.

Do not infer a missing field from page order, filenames, or another Experiment.

### 3. Build the workflow snapshot

`driver.load_workflow_snapshot(paths, package_id)` reads:

- Package lifecycle, phase, blocker, and version;
- Package-owned Experiment statuses;
- management-open Runs;
- each Run's canonical `status.json`.

Pass that snapshot to:

```bash
node workflow.ts next --json '<snapshot>'
```

The workflow ticket chooses launch, monitoring, result analysis, repair, plan handoff, or a user
decision. Dashboard server health is informational for execution. Repairing the human interface must
not stop a healthy Run.

### 4. Apply research-op envelopes

Every management change is an envelope:

```json
{
  "op": "update",
  "target": "experiments-status",
  "payload": {"id": "P1", "to": "ACTIVE"},
  "idempotency_key": "run:P1:active"
}
```

Validate it with `driver.validate_mutation()`. Compile it with
`driver.research_op_argv(paths, package_id, envelope)`, then run the returned command. Do not write
state files yourself.

If `research-op` rejects the command, use its rule and detail fields to repair the input or select the
correct handoff. Do not patch a projection to hide the rejection.

### 5. Keep Implementation and Tracker current

Materialize each Change plan before its first code edit. After every logical
edit batch, synchronize its code-location predicates:

```bash
python3 skills/research-run/scripts/implementation_status.py sync \
  --workspace . --research-root .research \
  --package <package-id>
```

Run declared TDD checks through the same helper; it records PASS or FAIL
against the current dependency fingerprint:

```bash
python3 skills/research-run/scripts/implementation_status.py verify \
  --workspace . --research-root .research \
  --package <package-id>
```

If a dependency changes after a passing check, the next sync marks that check
STALE and unchecks it. Before implementation review or launch readiness, run
`implementation_status.py check`; it fails unless every planned code location
and verification is currently PASS. Do not add a watcher, edit checkbox state
by hand, or infer completion from the generated page.

After every completed `To-Do` task, update its owner before selecting the next
task: synchronize and verify a Change, or reconcile the Run with `scan-events`.
Tracker then derives the same status automatically. Never write a separate
Tracker row, completion boolean, or current-task marker.

### 6. Check readiness and launch

Before launch, verify:

- Package lifecycle is `ACTIVE`;
- Package phase is `READY_TO_LAUNCH`;
- Experiment status is `READY`;
- the Experiment spec is complete;
- the Package has an open Scope Execution Lease that includes the Experiment;
  imported Packages without a lease require the legacy user launch acknowledgement;
- any requested GPU allocation is open and bound to this Package and Experiment.

The launcher enforces these conditions again:

```bash
python3 lib/experiments/launch.py \
  --workspace . \
  --research-root .research \
  --pkg <package-id> \
  --exp <experiment-id> \
  --tmux-session <name> \
  -- bash <command>
```

Use `--foreground` for a short command. Long runs should use the default tmux transport.

### 7. Monitor and reconcile

List management-open Runs:

```bash
python3 lib/experiments/report.py \
  --workspace . --research-root .research --open
```

Inspect one Run with:

```bash
python3 lib/experiments/report.py \
  --workspace . --research-root .research \
  --run .research/experiments/<package>/<experiment>/<run>
```

Use `status.json`, `events.jsonl`, `metrics.jsonl`, and `log.txt` from that Run. Raw tmux scrollback is
only a debugging aid.

At every check and after completion:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace . --research-root .research \
  --pkg <package-id> --op scan-events --payload '{}'
```

This repairs lost launch or terminal callbacks without introducing a second live index.

### 8. Extract and finalize Result tables

Read `skills/research-package/references/results-page-pattern.md` before
finalizing a schema-backed Result.

When the selected Experiment has a frozen `result_schema`, require its
evaluation script to write one comprehensive CSV with
`metric,value,unit,status,reason` plus every selector field used by the schema.
The file may contain extra metrics and rows.

After the Run is terminal, extract the exact human tables:

```bash
python3 -m lib.experiments.result_tables \
  --workspace . --research-root .research \
  --run-dir <run-dir> \
  --source <comprehensive-metrics.csv>
```

Then finalize the Run result with the returned manifest:

```bash
python3 -m lib.experiments.extract \
  --workspace . --research-root .research \
  --run-dir <run-dir> \
  --payload <result-payload.json> \
  --result-table-manifest <run-dir>/files/result-tables/manifest.json
```

Do not hand-write a derived table, copy values into HTML, or finalize a
schema-backed result without the manifest. Missing cells, duplicate matches,
unit mismatch, invalid cell status, schema drift, or hash drift are blockers,
not blank values to repair manually. After finalization, let
`research-dashboard` rebuild the human projection.

### 9. Verify and route

Read measured values from the verified `result.json` and its EvidenceRefs.
Compare them with the Experiment gate. Record the result through `research-op`;
the verifier must not rewrite the gate. A success route requires a state-backed
`VERIFIER_VERDICT` Decision bound to the finalized Run event, result hash,
Experiment scope version, gate, measured value, and control mode.

If another Experiment remains, route back to readiness. Otherwise record a terminal Package outcome or
the exact blocker. A deferred run should record its continuation as structured state, including the
current Experiment, evidence, blocker, and next check time.

## Role report contract

Every dispatched role returns:

```json
{
  "agent_role": "review",
  "assigned_scope": "package-id::P1",
  "source_seq": 42,
  "source_hash": "<state hash>",
  "sourceDirection": "direction-id",
  "sourceExperiment": "package-id::P1",
  "status": "ROLE_OK",
  "evidence": ["state/notes/<sha256>.md"],
  "blockers": [],
  "recommended_next_action": "launch",
  "mutations": []
}
```

Roles provide evidence and proposed commands. The main run controller decides whether to accept them.
Use a separate reviewer for implementation review.

## Stop condition

A tick may stop when:

- every completed Run has been reconciled and its evidence is recorded;
- no `scan-events` action remains pending;
- each open Run has a scheduled next check;
- the Package is terminal, waiting on a named decision, or blocked by a concrete external condition.

Waiting by itself is not a terminal outcome.

## Durable data

| Data | Location |
| --- | --- |
| Management events | `.research/state/events.jsonl` |
| Current projection | `.research/state/current.json` |
| Command audit | `.research/audit/actions.jsonl` |
| Run metadata | `.research/experiments/<package>/<experiment>/<run>/run.json` |
| Frozen run context | `.research/experiments/<package>/<experiment>/<run>/context.json` |
| Live status and measurements | the same Run directory |

The interface can be deleted and rebuilt without changing this procedure.
