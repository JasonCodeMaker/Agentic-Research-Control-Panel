# Research package contract

## Definition

A research package is one Package aggregate across draft and executable
states. Before it exists, a standalone Brainstorm owns the idea document.
On user request, the agent materializes that exact revision into a `DRAFT`
Package without creating another approval boundary. In `DRAFT`, it owns the
proposal document but no Direction, Experiment, or execution authority. A
later `SCOPE_BUNDLE_COMMIT` transaction commits the full Scope Bundle and binds
its Experiments to that same aggregate.

```json
{
  "purpose": "what the experiment must establish",
  "config_ref": "immutable configuration reference",
  "gate": "one measurable acceptance predicate",
  "control_mode": "SUPERVISED | CHECKPOINTED | DEFERRED | AUTONOMOUS"
}
```

Observed values do not belong in the spec. They belong in run result records
and cited evidence.

## Storage model

```text
.research/
  state/
    research.sqlite3
    events.jsonl
    current.json
    notes/
  audit/
    actions.jsonl
  experiments/
    <package-id>/
      <experiment-id>/
        <run-id>/
          result.json
          ...
  interface/
    index.html
    packages/<package-id>/
      index.html
      plan.html
      implementation.html
      results.html
      analysis.html
      tracker.html
      docs/index.html
      docs/proposal.html
      _agent/context.html
```

SQLite is management authority. `events.jsonl`, `current.json`, and
`actions.jsonl` are compatibility exports. Experiment directories hold
execution evidence. The interface is generated for human inspection and may
be deleted and rebuilt.

No research operation may infer management state from HTML. The package
lifecycle skills never read or write the generated interface.

## Draft and activation contract

A Draft Package must satisfy:

```text
lifecycle == DRAFT
phase == null
blocker == null
executionAuthorized == false
direction_id == null
sourceExperiments == []
documentPath == docs/proposal.html
```

Every refinement advances `draftRevision` and remains `REFINING`. One full
Scope review binds the exact `{id, draft_revision, document_sha256}` shown to
the user and contains the complete Direction plus all selected Experiments.
Review commit fails closed if this source changes.

Materialization seeds the complete standard Package page set. Empty Results and
Analysis pages render their planned or empty states; they do not require a
later page-selection mutation. The Analysis initializer remains only as an
idempotent repair path for older Package records.

Activation preserves the same Package id, `documentPath`, and `document_note`.
One `TransactionCommitted` event records the exact Draft as `SCOPE_READY`,
commits Direction and Experiment Scope, sets the Package to
`ACTIVE / CONTEXT_LOADED`, records `scopeBinding`, applies Experiment bindings,
and opens an Execution Lease over the reviewed Experiment ids. It creates no
Proposal aggregate, never creates a second Package, and never exposes a
partially committed Scope Bundle. `PackageActivated` remains a compatibility
event for imported and historical paths.

A user may reopen an `ACTIVE` Package as the same Draft only before execution:
there must be no Run history, result evidence, terminal Experiment state, or
Package blocker. The atomic `PackageReopenedAsDraft` event preserves the
proposal NoteRef, clears Package execution and Scope bindings, and detaches its
Experiments. Their accepted Scope remains visible in history, while
`scope_confirmation=STALE` and `status=BLOCKED` prevent accidental reuse. Any
later activation therefore requires a fresh hash-bound Scope review of the
revised Draft. That Scope Bundle may atomically commit the next version of the
same Direction and re-confirm the next versions of its detached Experiments;
it does not require replacement ids or separate approvals.

## Scope activation

On first activation, each proposed Experiment is new, version 1, parented by
the new Direction, and committed in the same composite event that binds it to
the Package. After a pre-run reopen, the same composite review may revise the
existing Direction and detached Experiments at their next Scope versions. The
compatibility path for independently committed Scope accepts an
existing Experiment only when all three predicates hold:

```text
direction_id == requested Direction
package_id is empty
scope_status == ACTIVE
```

Neither path creates a package-local copy of Experiment intent. The normal path
creates the one canonical Experiment aggregate; compatibility activation binds
the existing canonical aggregate.

| Accepted Experiment field | Activation effect |
| --- | --- |
| canonical Experiment id | unchanged |
| four-field `spec` | unchanged |
| empty `package_id` | new Package id |
| no execution-local handle | deterministic `local_id` |

The new local ids are deterministic (`P0`, `P1`, and so on) in the reviewed
proposal order. Materialization does not create an `after` edge. Dependencies
must be declared through a governed package plan, not inferred from order.

The Package records Direction provenance through `sourceDirection`,
`sourceVersion`, and `sourceChange`. Its `sourceExperiments` field is a
minimal index of accepted Experiment `id`, `version`, and `source`. It never
embeds a Scope node or a copied spec.

## Package aggregate

The Package owns package-level decision context:

- identity: `id`, `slug`, `name`, `title`, `tag`, and `tagMeaning`;
- lifecycle: `lifecycle`, `phase`, and `blocker`;
- research intent: `problem`, `motivation`, `objective`, and `hypothesis`;
- evaluation summary: `primaryMetric`, `baseline`, `budget`, and
  `activeGate`;
- execution summary: `nextAction`, `lastAction`, `openRuns`, and
  `currentBlocker`;
- evidence roots: `sourcePath`, `artifactRoot`, and `runtime`;
- Direction provenance when activated from Scope; and
- `pages`, the desired human projection page set.

Before activation, the Package instead carries `draftStatus`, `draftRevision`,
`documentPath`, `document_note`, and `executionAuthorized=false`. Its free-form
document may contain plans, tables, figures, risks, and open questions without
turning them into premature Scope fields.

Package metadata may summarize a result for navigation, but it must cite the
owning Experiment result. It must not become an independent measurement
store.

### Research Intent

Research Intent records the reasoning chain that makes a Package worth
executing. The four fields have different jobs:

- **Problem** identifies a known or high-probability research limitation, gap,
  or unresolved capability. It says what is wrong or missing at the research
  level; it is not an implementation task or a provenance note.
- **Motivation** explains why that Problem matters and may state the high-level
  solution rationale: why the proposed method family could plausibly address
  it. Detailed implementation and evaluation settings remain in Scope and
  Plan.
- **Objective** states the verifiable target used to judge whether the
  Motivation's proposed solution was realized. It names the target object and
  necessary boundaries without presuming a positive result.
- **Hypothesis** is the concise, falsifiable natural-language synthesis of the
  Motivation's high-level solution and the Objective's expected observable
  outcome. It is the Package copy of `Direction.spec.hypothesis`, not an
  independent fourth source of intent.

An activated Package must contain all four fields. They must be semantically
distinct and may not fall back to one another when content is missing. The
Package Hypothesis must equal the accepted Direction hypothesis. A completed
Package may conclude that the Hypothesis is supported, not supported, or only
conditionally supported; execution completeness and hypothesis support are
separate judgments.

### Canonical identity

New Packages use `identityContractVersion=1`. Before conversion, the agent
reads the Project, proposed Direction, selected Experiments, and proposal. It
then writes one short `identityRationale` that identifies the Package's main
purpose and designs a title around that purpose.

The mechanical contract is:

```text
name == title
slug == id
id == <identityDate>-<title>
```

`identityDate` is the Package's original creation or materialization date in
real `YYYY-MM-DD` form. It stays fixed when an identity is corrected. `title`
is a case-preserving, hyphen-separated sequence of ASCII alphanumeric tokens,
such as `Reproducing-VideoSearch-R1`. The date is not part of `name` or
`title`.

The title names the bounded core purpose. It does not need to list every
dataset, control, budget, or later Experiment. Those details remain in Scope
and the Package plan. It must not claim an outcome that has not been measured.

### Package abstract and Hero lead

`abstract` is the Package-level Abstract / TLDR and the source for the Overview
Hero lead. It is one natural-English paragraph of no more than 150 words. It
describes the whole Package in execution order: the initial work, the follow-up
work, and the question the combined work will answer.

The abstract is not a copy of `problem`, `objective`, or the Direction
hypothesis. It does not carry the complete protocol, baseline roster, metric
definition, or gate, and it does not claim an outcome before measurement.
Those facts remain in their typed Scope, Plan, and Experiment homes. A legacy
Package without `abstract` may render `problem` as a compatibility fallback.

A pre-run identity correction uses one user-approved transaction. The event
removes the old Package key, creates the new canonical key, and updates every
bound Experiment and evidence target together. It is rejected after a Run,
result summary, blocker, started Experiment, or evidence directory exists.
The Direction and Experiment specs do not change. The old identity remains in
`identityHistory` and event history.

## Experiment aggregate

The canonical aggregate id is the accepted Scope Experiment id. The record
stores:

- `id` and `local_id`;
- `package_id`;
- `direction_id` and Scope version/source/confirmation;
- the four-field `spec`;
- canonical execution `status`;
- optional declared dependencies in `after`;
- an evidence `output` path;
- optional renderer metadata and result schema.

`local_id` is a Package-local execution handle, not a second identity.
`aliases` may exist only on migrated legacy records and is read-only
compatibility data.

## Implementation Change aggregate

Implementation intent and its observable status live in the existing `Change`
aggregate; there is no second checklist or UI-state aggregate:

```json
{
  "id": "<package>::change::<local-id>",
  "local_id": "<local-id>",
  "package_id": "<package-id>",
  "order": 1,
  "title": "Concise implementation unit",
  "validating_experiments": ["<canonical-experiment-id>"],
  "plan": {
    "how_it_changes": "Concrete behavioral and structural delta.",
    "code_locations": [
      {
        "id": "stable-location-id",
        "action": "REUSE | ADD | MODIFY | LINK | OUTPUT",
        "root": "workspace | research",
        "path": "relative/path",
        "predicate": "exists | git_clean",
        "baseline": {"kind": "MISSING | FILE | DIRECTORY | SYMLINK"}
      }
    ],
    "verifications": [
      {
        "id": "stable-check-id",
        "label": "What correctness means",
        "depends_on": ["stable-location-id"],
        "command": ["python3", "-m", "pytest", "-q", "tests/test_unit.py"]
      }
    ]
  },
  "observations": {
    "code_locations": {
      "stable-location-id": {
        "state": "PASS | PENDING",
        "fingerprint": "<current-input-digest>",
        "reason": "predicate result"
      }
    },
    "verifications": {
      "stable-check-id": {
        "state": "PASS | FAIL | PENDING | STALE",
        "input_fingerprint": "<dependency-digest>",
        "reason": "check result"
      }
    }
  }
}
```

The gateway freezes baselines when the plan is first committed, before code is
edited. `ADD` passes only when an absent baseline now exists; `MODIFY` passes
only when content differs from its baseline; `LINK` requires a resolving
symlink; `OUTPUT` requires the declared artifact; and `REUSE` requires the
declared source, optionally with a clean Git predicate.

After each logical edit batch, `research-run` recomputes code observations.
Verification PASS is bound to its dependency fingerprint. A later input change
makes that observation STALE. The generated checkbox is therefore a projection
of reproducible state, never a stored boolean or user-editable control.

Tracker has no aggregate of its own. Its `To-Do` joins the ordered Package
Experiments, these Change observations, and Run/Result evidence. Progress and
the current task are derived values; completing work means updating the owning
Change or Run, not writing a Tracker row.

## Result evidence

Each Experiment may declare zero or more human Result tables through its
optional `resultSchema`. The schema fixes table type, rows, selectors, metrics,
units, and nullability before the first Run. It contains no measured values.
Once any Run exists for that Experiment, the schema is immutable.

The canonical finalized result path is:

```text
.research/experiments/<package-id>/<experiment-id>/<run-id>/result.json
```

The evaluation script writes a comprehensive metric CSV inside the Run
evidence boundary. The Result extractor uses the schema frozen in
`context.json` to produce one derived CSV per declared table plus a manifest.
`result.json` binds that manifest, every derived table, and the comprehensive
source as hashed EvidenceRefs.

A human Result table is a projection of those verified files. It never owns a
value. Before measurement, the complete table shape renders with null values.
After finalization, a value renders only when the schema hash, Run identity,
source, manifest, and table hashes verify. Read
[Results page pattern](results-page-pattern.md) for the exact schema and
extraction contract.

## Human page contract

Preserve all page names and navigation while keeping each stage page limited
to its approved content model.

| Page | Human decision it supports |
| --- | --- |
| `index.html` | Research Intent, status summary, source path, and evidence root |
| `plan.html` | ordered Experiment contracts, gates, dependencies, controls, and evidence destinations |
| `implementation.html` | code locations, intended changes, and verification status by Experiment |
| `results.html` | schema-backed Result tables grouped by Experiment |
| `analysis.html` | evidence-backed insights and adopted rules |
| `tracker.html` | current `To-Do` task and intermediate artifact locations by Experiment |
| `docs/index.html` | source and contract document index |
| `_agent/context.html` | retained historical compatibility route; not a Package module or context source |

The `_agent` filename and legacy `data-audience="agent"` selectors may remain
for route and DOM compatibility. Package pages do not render Agent Content or
Agent context modules. The compatibility route is not an agent context source
and does not grant HTML authority.

### Single-home rule

Each field has one human home:

- Research Intent, identity, and evidence roots: `index.html`;
- the ordered executable Experiment contracts and their canonical configuration references: `plan.html`;
- code locations, implementation decisions, and verification status: `implementation.html`;
- verified Result tables and their cell states: `results.html`;
- insights and rules: `analysis.html`;
- current task and intermediate Run file locations: `tracker.html`; and
- source document summaries: `docs/index.html`.

Other pages link to that home. They do not maintain another copy.

### Stable layout rules

- Keep the status strip and package navigation on every stage page.
- Keep the Implementation map grouped by Experiment with native disabled
  checkboxes.
- Keep Tracker titled `To-Do`, grouped by Experiment, with one current task
  when tasks exist and native disabled checkboxes derived from Change and Run
  evidence.
- Keep Result tables grouped by Experiment.
- Keep main tables open and ablation tables collapsed by default.
- Keep all existing stable anchors unless a renderer migration updates every
  caller in the same change.

Copy may change to reflect the storage contract. Further page-structure or
visual changes require explicit user approval.

## Rendering boundary

The renderer may read management state and Experiment evidence, then rebuild:

```text
.research/interface/
```

Rendering is one-way:

```text
state + experiment evidence -> human interface
```

Edits to generated HTML never flow back into state. Package state records the
desired `pages` list but does not invoke the renderer.

## Mutation rules

- Create Packages and bind accepted Experiments through the management
  gateway.
- Reopen only a never-run Package through `PackageReopenedAsDraft`; do not
  simulate rollback with package patches or direct Experiment edits.
- Change governed intent through Scope.
- Update Experiment execution status through the management gateway; never
  revise its `spec` through a Package row operation.
- Write run evidence below `.research/experiments/`.
- Rebuild human pages through the interface owner.
- Never edit `research.sqlite3`, `events.jsonl`, `current.json`, or generated
  HTML by hand.
- Never add a second persisted context pack.

## Acceptance checks

A package activation change is valid when:

1. the same Draft Package id becomes ACTIVE in transactional current state;
2. the reviewed document NoteRef and path are unchanged;
3. every Experiment has a complete four-field spec;
4. every bound Experiment keeps its accepted Scope id and has exactly one
   Package/local-id binding;
5. no dependency was invented;
6. evidence paths resolve below `.research/experiments/`;
7. the open Execution Lease contains exactly the reviewed Experiment ids;
8. activation did not read generated HTML; and
9. a later renderer rebuild can reproduce the same human page hierarchy and
   proposal document.
