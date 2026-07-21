---
name: research-package
description: "Use when creating or materially restructuring a state-backed research package from a ratified Direction or explicit package input."
argument-hint: "[from-scope <direction-id> | create <package-name>]"
---

# Research package

A research package is a governed Package aggregate bound to one or more
accepted Scope Experiment aggregates. It is not an HTML directory, and
materialization does not create a second Experiment object.

Use this skill to create that management state. A separate renderer owns the
human interface.

## Storage and authority

The workspace-local root is `.research/`:

```text
.research/
  state/         committed management events and rebuildable state
  audit/         command audit records
  experiments/   run evidence and experiment products
  interface/     generated pages for human inspection
```

The authority order is:

1. `.research/state/events.jsonl`
2. `.research/state/current.json`, which must equal a fold of the events
3. `.research/experiments/<package>/<experiment>/<run>/result.json` and the
   evidence referenced by that result
4. `.research/interface/`, which is a disposable human projection

This skill may read and mutate management state through the management
gateway. It may create Experiment evidence paths in state. It must not read,
edit, or render `.research/interface/`.

Do not recover package state from HTML. Do not persist an agent context pack.
Load context on demand:

```bash
python3 -m lib.research_state.cli \
  --workspace <cwd> \
  context <package-id> \
  --phase <phase>
```

## Choose the creation path

Use `from-scope` when a ratified Direction already exists. This is the normal
path because it preserves governed intent and provenance.

Use manual creation when the user explicitly needs to supply Package metadata
instead of accepting the defaults from `from-scope`. It still requires an
active ratified Direction and accepted Experiments; “manual” does not bypass
Scope.

Every new Package starts at `ACTIVE / CONTEXT_LOADED` with no blocker.
READY_TO_LAUNCH and terminal states are transitions backed by Change and
Decision aggregates; historical Packages enter those states only through the
explicit migration path.

## Create from Scope

Check readiness first:

```bash
python3 skills/research-package/scripts/create_from_scope.py \
  --workspace <cwd> \
  --direction-id <direction-id> \
  --check \
  --json
```

The check is materializable only when:

- the Direction exists and is `ACTIVE`;
- at least one Experiment aggregate has `direction_id` equal to the Direction;
- that Experiment has an empty `package_id`;
- that Experiment has `scope_status == "ACTIVE"`; and
- no Package with the requested id exists.

Pending proposals are not authority. If a Direction or Experiment is missing
or pending, return to `research-scope`.

Materialize:

```bash
python3 skills/research-package/scripts/create_from_scope.py \
  --workspace <cwd> \
  --direction-id <direction-id> \
  --id <package-id>
```

For every accepted Scope Experiment, materialization:

- assigns a package-local id in deterministic order, starting at `P0`;
- keeps the accepted Scope Experiment id as the canonical aggregate id;
- retains its existing four-field `spec` without copying it;
- adds only the Package binding, local id, execution status, and evidence
  metadata;
- sets the evidence target to
  `.research/experiments/<package>/<local-id>/<run-id>/result.json`;
- does not create a package-scoped Experiment clone; and
- does not invent an `after` edge that Scope did not state.

The Package records `sourceDirection`, `sourceVersion`, `sourceChange`, and a
minimal `sourceExperiments` index containing only accepted Experiment id,
version, and source. The bound Experiment's `package_id` is the inverse link.

## Manual creation

Create one Package and bind its accepted Experiments in one command:

```bash
python3 skills/research-package/scripts/create_research_package.py \
  --workspace <cwd> \
  --id 2026-07-20-example \
  --name "Example" \
  --category in-progress \
  --tag method \
  --tag-meaning "Method validation" \
  --problem "What is not yet known" \
  --objective "What decision this package must support" \
  --motivation "Why the decision matters" \
  --hypothesis "One falsifiable claim" \
  --primary-metric "Recall@10" \
  --source-direction "direction/example" \
  --source-version 1 \
  --source-change "<current-direction-event-id>" \
  --source-experiments '[{
    "id": "experiment/example/baseline",
    "version": 1,
    "source": "triage:experiment-example-baseline"
  }]' \
  --experiments '[{
    "scope_experiment_id": "experiment/example/baseline",
    "local_id": "P0",
    "output": ".research/experiments/2026-07-20-example/P0/<run-id>/result.json",
    "status": "READY",
    "measures": true
  }]' \
  --scope index,plan,results,tracker,docs,_agent
```

Manual package ids use `YYYY-MM-DD-slug`. The `--experiments` value is a JSON
array of bindings. Every row requires `scope_experiment_id` and `local_id`.
The referenced accepted Experiment already owns `purpose`, `config_ref`,
`gate`, and `control_mode`; supplying any of those fields here is rejected.

Optional renderer metadata such as `label`, `output`, `measures`,
`requiresCode`, `complex`, `resultSchema`, `runLink`, and `docsAnchor` stays
on the Experiment record. It does not create a second source of intent.

## Experiment result design

For each measurable Experiment, define the decision before running it:

- `purpose`: the question the run answers;
- `config_ref`: an immutable config or content-addressed reference;
- `gate`: one measurable acceptance predicate;
- `control_mode`: `SUPERVISED`, `CHECKPOINTED`, `DEFERRED`, or `AUTONOMOUS`;
- `resultSchema`: optional table shape and provenance requirements; and
- `output`: the expected result record below `.research/experiments/`.

The result record and cited evidence own observed values. Package metadata may
describe the planned table but must not contain a competing copy of measured
results.

Do not add a dependency unless it is part of the accepted plan. A missing
`after` field means no declared dependency. It does not mean "after the
previous Experiment".

## Human projection contract

`--scope` records which human pages the package should expose. It does not
write those pages. The stable page set is:

- `index.html`
- `plan.html`
- `implementation.html`
- `results.html`
- `analysis.html`
- `tracker.html`
- `docs/index.html`
- `_agent/context.html`, retained as a historical filename for a human audit
  page

Keep the existing page hierarchy, sections, cards, tables, navigation, and
`data-*` anchors. The storage redesign changes data sources and paths, not
the human layout. The renderer may rebuild these pages under
`.research/interface/packages/<package-id>/`.

The bundled templates are renderer inputs. This skill does not populate or
inspect rendered HTML.

See:

- [Package contract](references/package-contract.md)
- [Results page pattern](references/results-page-pattern.md)

## Mutation boundary

After creation, route package and Experiment changes through `research-op`.
Do not hand-edit `events.jsonl` or `current.json`.

Use Scope again when the research intent changes. Package edits may refine
execution details, but they must not silently replace the accepted Direction
or Scope Experiment gate.

Removed compatibility options are intentionally unsupported. Use only the
arguments shown by the current entrypoint help.

## Validation

Run:

```bash
python3 -m pytest -q tests/research-package
python3 -m py_compile \
  skills/research-package/scripts/create_from_scope.py \
  skills/research-package/scripts/create_research_package.py
python3 -m lib.research_state.cli \
  --workspace <cwd> \
  show package <package-id>
```

Then verify the package-scoped Experiment:

- keeps the accepted Scope Experiment aggregate id;
- has `package_id=<package-id>` and the assigned `local_id`;
- has the exact four-field `spec`;
- points to `.research/experiments/`;
- has no invented dependency; and
- has no duplicate package-scoped intent record.

Do not validate creation by opening the human interface. A renderer check is
a separate interface-owner concern.

## Final response

Report:

- package id and committed event id;
- bound Experiment aggregate ids;
- Scope Direction and accepted Experiment provenance;
- experiment evidence root;
- selected human page metadata;
- validation commands and results; and
- any unresolved Scope or evidence questions.
