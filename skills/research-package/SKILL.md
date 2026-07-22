---
name: research-package
description: "Use when converting a Brainstorm, refining a Draft Package, atomically finalizing Scope, or restructuring a state-backed Package."
---

# Research package

A research package is one governed Package aggregate created only after a user
approves conversion of a standalone Brainstorm. It begins as a non-executable
`DRAFT` with a full proposal document, then becomes `ACTIVE` when one later
approval atomically commits Direction, Experiments, and Package activation.
It is not an HTML directory, and activation does not create a second Package.

Use this skill to activate or restructure that management state. A separate
renderer owns the human interface.

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

Omit `--phase` while the Package is still `DRAFT`.

## Normal lifecycle

The normal path has two distinct user approvals:

```text
standalone Brainstorm + refinement
  -> approval 1: PackageDraftCreated consumes the exact Brainstorm
  -> Draft Package DRAFT / REFINING + refinement
  -> one source-bound Direction-and-Experiments proposal review
  -> approval 2: one PackageActivated event records DRAFT / SCOPE_READY,
     accepts the proposal, commits Direction and Experiments, and leaves
     the same Package ACTIVE / CONTEXT_LOADED
```

Do not collapse Brainstorm creation into Package creation. Do not separately
accept Direction, accept each Experiment, and then activate the Package on the
normal path. The full proposal and its hash bind all four effects to one user
decision and one atomic event.

### Approval 1: convert Brainstorm to Draft Package

After the user approves the exact Brainstorm revision:

```bash
python3 skills/research-package/scripts/draft_package.py \
  --workspace <cwd> convert \
  --brainstorm-id <brainstorm-id> \
  --actor-id <stable-user-id>
```

This transfers the NoteRef to `docs/proposal.html`, consumes the standalone
Brainstorm, and creates `DRAFT / REFINING` with no Scope or execution authority.

Refine that same Package in place:

```bash
python3 skills/research-package/scripts/draft_package.py \
  --workspace <cwd> revise \
  --package-id <package-id> \
  --patch '<json-object>' \
  --body-file <proposal-fragment.html>
```

Every content change advances `draftRevision` and keeps `draftStatus=REFINING`.
Do not manually set `SCOPE_READY`; final approval owns that transition.

### Approval 2: finalize Scope and activate

Build one proposal containing the complete new Direction and all selected
Experiment nodes:

```bash
python3 skills/research-package/scripts/draft_package.py \
  --workspace <cwd> build-proposal \
  --package-id <package-id> \
  --direction '<complete-direction-node>' \
  --experiments '<complete-experiment-node-array>'
```

Submit that proposal through `research-scope` Triage and show one semantic
review. After the user explicitly approves it, use the hidden receipt once:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <cwd> --pkg <package-id> --op package-finalize \
  --from-triage <proposal-id> --proposal-hash <proposal-hash> \
  --actor-type user --actor-id <stable-user-id>
```

`package-finalize` fails closed if the Draft revision, document hash, proposal,
Direction, or any Experiment changed after review. Retrying the identical
command is idempotent and does not require another approval.

Use manual creation only for compatibility or imported state when the user
must supply Package metadata. It still requires an active ratified Direction
and accepted Experiments; "manual" does not bypass Scope.

Every activated Package starts at `ACTIVE / CONTEXT_LOADED` with no blocker.
Before activation it remains `DRAFT`, has no execution phase, and cannot be
launched.
READY_TO_LAUNCH and terminal states are transitions backed by Change and
Decision aggregates; historical Packages enter those states only through the
explicit migration path.

### Reopen a pre-launch Package as Draft

If the user finds a material design problem after activation but before any
Run or result exists, reopen the same Package instead of creating a replacement
or editing Scope-bound fields in place:

```bash
python3 skills/research-package/scripts/reopen_as_draft.py \
  --workspace <cwd> \
  --package-id <package-id> \
  --reason "<why the proposal needs another alignment pass>" \
  --actor-id <user-id>
```

`PackageReopenedAsDraft` atomically restores `DRAFT / REFINING`, revokes
execution authority, preserves the governed proposal NoteRef, and detaches the
bound Experiments. Detached Experiments retain their accepted Scope history but
become `STALE / BLOCKED`, so the old Scope cannot be rebound without a fresh
review. The transition requires an explicit user actor and fails closed when
any Run, result, terminal Experiment state, or unresolved blocker exists.

## Compatibility: create or activate from already committed Scope

`create_from_scope.py` remains for imported or older workspaces whose Direction
and Experiments were separately ratified before Package activation. It is not
the normal two-approval path. Check readiness first:

```bash
python3 skills/research-package/scripts/create_from_scope.py \
  --workspace <cwd> \
  --direction-id <direction-id> \
  --check \
  --json
```

The check is activatable only when:

- the Direction exists and is `ACTIVE`;
- at least one Experiment aggregate has `direction_id` equal to the Direction;
- that Experiment has an empty `package_id`;
- that Experiment has `scope_status == "ACTIVE"`; and
- the requested Package exists as `DRAFT` and still matches the accepted
  Direction's source binding; or the caller is using the legacy no-draft
  compatibility path.

Pending proposals are not authority. If a Direction or Experiment is missing
or pending, return to `research-scope`.

Activate:

```bash
python3 skills/research-package/scripts/create_from_scope.py \
  --workspace <cwd> \
  --direction-id <direction-id> \
  --id <package-id>
```

For every accepted Scope Experiment, activation:

- assigns a package-local id in deterministic order, starting at `P0`;
- keeps the accepted Scope Experiment id as the canonical aggregate id;
- retains its existing four-field `spec` without copying it;
- adds only the Package binding, local id, execution status, and evidence
  metadata;
- sets the evidence target to
  `.research/experiments/<package>/<local-id>/<run-id>/result.json`;
- does not create a package-scoped Experiment clone; and
- does not invent an `after` edge that Scope did not state.

The activated Package records `sourceDirection`, `sourceVersion`,
`sourceChange`, and a minimal `sourceExperiments` index containing only the
accepted Experiment id, version, and source. The bound Experiment's
`package_id` is the inverse link.

It also records `scopeBinding`, which connects the exact reviewed draft to the
ratified Direction version and ordered Experiment ids. `PackageActivated`
replaces the Draft state and binds all Experiments in one event. The proposal
document stays at `docs/proposal.html` with the same content-addressed NoteRef.

### Compatibility transfer into an existing Package

Older workspaces may still contain standalone `brainstorm` aggregates. When
an accepted legacy Direction proposal names `source_brainstorms`,
`from-scope` derives those ids from the accepted proposal. Do not make the
operator repeat them or silently default the provenance to an empty list.

Package materialization transfers each source document in the same
`PackageMaterialized` event:

- `sourceBrainstorms` becomes a Package-owned provenance index;
- the exact content-addressed `document_note` is registered under
  `interface_notes` at `docs/<brainstorm-slug>.html`;
- `docsGroups` exposes it as a `Source proposal` document;
- the Brainstorm aggregate is removed from current state, so it no longer has
  a Dashboard card or standalone route; and
- append-only event history and the note blob remain available for audit.

The transferred document is historical planning context. The ratified
Direction and Experiment Scope remain the authority for execution, especially
when later Scope review relaxed or replaced statements in the draft.

Never remove a Brainstorm before the Package record owns the same NoteRef. A
missing, archived, or changed source Brainstorm blocks materialization.

`--source-brainstorms` is a compatibility input for older Directions without
typed proposal provenance. When typed provenance exists, an explicit value must
match it exactly and cannot omit a source.

## Manual compatibility creation

Use this only for explicit compatibility or imported state that has no Draft
Package. Create one Package and bind its accepted Experiments in one command:

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

After activation, route package and Experiment changes through `research-op`.
Do not hand-edit `events.jsonl` or `current.json`.

If an older Package was materialized before source-document transfer existed,
repair it only with the governed transfer command:

```bash
python3 skills/research-package/scripts/brainstorm_transfer.py \
  --workspace <cwd> \
  --package-id <package-id> \
  --brainstorm-id <brainstorm-id> \
  --actor-id <user-id>
```

This explicit repair requires a user actor and atomically updates Package docs
while removing the standalone Brainstorm. Do not emulate it with separate
`doc-file`, archive, and delete operations.

Before activation, refine research intent in the Draft Package document and
submit a fresh Scope review whenever the bound revision changes. After
activation, use Scope again when research intent changes. Package edits may
refine execution details, but they must not silently replace the accepted
Direction or Scope Experiment gate.

Removed compatibility options are intentionally unsupported. Use only the
arguments shown by the current entrypoint help.

## Validation

Run:

```bash
python3 -m pytest -q tests/research-package
python3 -m py_compile \
  skills/research-package/scripts/draft_package.py \
  skills/research-package/scripts/create_from_scope.py \
  skills/research-package/scripts/brainstorm_transfer.py \
  skills/research-package/scripts/reopen_as_draft.py \
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

When source Brainstorms were declared, also verify:

- `sourceBrainstorms` contains Package-owned descriptors, not copied active
  Brainstorm aggregates;
- `docsGroups` contains the `source-proposal` group;
- the Package owns every transferred NoteRef through `interface_notes`;
- no current Brainstorm aggregate remains for a converted source; and
- Brainstorm history includes the composite Package event.

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
