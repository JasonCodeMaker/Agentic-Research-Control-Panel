# Research package contract

## Definition

A research package is one Package aggregate bound to accepted Scope
Experiments. The Package groups a research decision. Each Experiment defines
one executable validation with this intent spec:

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
      _agent/context.html
```

The state event log is authoritative. `current.json` is a verified,
rebuildable fold. Experiment directories hold execution evidence. The
interface is generated for human inspection and may be deleted and rebuilt.

No research operation may infer management state from HTML. The package
creation skill never reads or writes the interface.

## Scope materialization

An accepted Scope Experiment is eligible for materialization only when all
three predicates hold:

```text
direction_id == requested Direction
package_id is empty
scope_status == ACTIVE
```

Materialization binds the existing accepted Experiment to the Package. It
does not create, move, or copy a second Scope aggregate.

| Accepted Experiment field | Materialization effect |
| --- | --- |
| canonical Experiment id | unchanged |
| four-field `spec` | unchanged |
| empty `package_id` | new Package id |
| no execution-local handle | deterministic `local_id` |

The new local ids are deterministic (`P0`, `P1`, and so on). Scope order is
the accepted Experiment id sort order. Materialization does not create an
`after` edge. Dependencies must be declared through a governed package plan,
not inferred from sort order.

The Package records Direction provenance through `sourceDirection`,
`sourceVersion`, and `sourceChange`. Its `sourceExperiments` field is a
minimal index of accepted Experiment `id`, `version`, and `source`. It never
embeds a Scope node or a copied spec.

## Package aggregate

The Package owns package-level decision context:

- identity: `id`, `name`, `tag`, and `tagMeaning`;
- lifecycle: `lifecycle`, `phase`, and `blocker`;
- research question: `problem`, `objective`, `motivation`, and `hypothesis`;
- evaluation summary: `primaryMetric`, `baseline`, `budget`, and
  `activeGate`;
- execution summary: `nextAction`, `lastAction`, `openRuns`, and
  `currentBlocker`;
- evidence roots: `sourcePath`, `artifactRoot`, and `runtime`;
- Direction provenance when materialized from Scope; and
- `pages`, the desired human projection page set.

Package metadata may summarize a result for navigation, but it must cite the
owning Experiment result. It must not become an independent measurement
store.

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

## Result evidence

The canonical run result path is:

```text
.research/experiments/<package-id>/<experiment-id>/<run-id>/result.json
```

`result.json` should identify the metric reading, gate outcome, validity,
config reference, code revision, checkpoint or model reference, dataset
reference, and paths to supporting evidence. Large checkpoints, logs, plots,
and tables may sit beside it or below the same run directory.

A human result table is a projection of these records. It never owns a value.
If the displayed value cannot be traced to a run record and its evidence, it
must remain `unmeasured`.

## Human page contract

The storage change does not alter the human layout. Preserve page names,
navigation, section order, cards, tables, and stable `data-*` anchors.

| Page | Human decision it supports |
| --- | --- |
| `index.html` | identity, status summary, source path, and evidence root |
| `plan.html` | hypothesis, metric contract, baseline, and Experiment plan |
| `implementation.html` | owned files, change review, tests, and adjudication |
| `results.html` | result gates, Experiment results, validity, and figures |
| `analysis.html` | evidence-backed insights and adopted rules |
| `tracker.html` | execution state, readiness, allocation, live checks, and route |
| `docs/index.html` | source and contract document index |
| `_agent/context.html` | human continuity and verification summary under a retained historical filename |

The `_agent` filename and legacy `data-audience="agent"` selectors may remain
for DOM compatibility. They denote collapsed audit detail for the human
reader. They are not an agent context source and do not grant HTML authority.

### Single-home rule

Each field has one human home:

- identity and evidence roots: `index.html`;
- hypothesis and plan: `plan.html`;
- owned files and implementation decisions: `implementation.html`;
- result verdicts and validity classes: `results.html`;
- insights and rules: `analysis.html`;
- live execution state and chosen route: `tracker.html`; and
- source document summaries: `docs/index.html`.

Other pages link to that home. They do not maintain another copy.

### Stable layout rules

- Keep the status strip and package navigation on every stage page.
- Keep the current conditional collapsed-detail structure.
- Keep the strict tracker checkbox markup.
- Keep result-gate rows at one row per planned Experiment.
- Keep supplementary result tables collapsed by default.
- Keep all existing stable anchors unless a renderer migration updates every
  caller in the same change.

Copy may change to reflect the new storage contract. Page structure and visual
design do not.

## Rendering boundary

The renderer may read management state and Experiment evidence, then rebuild:

```text
.research/interface/
```

Rendering is one-way:

```text
state + experiment evidence -> human interface
```

Edits to generated HTML never flow back into state. Package creation records
the desired `pages` list but does not invoke the renderer.

## Mutation rules

- Create Packages and bind accepted Experiments through the management
  gateway.
- Change governed intent through Scope.
- Update Experiment execution status through the management gateway; never
  revise its `spec` through a Package row operation.
- Write run evidence below `.research/experiments/`.
- Rebuild human pages through the interface owner.
- Never edit `events.jsonl`, `current.json`, or generated HTML by hand.
- Never add a second persisted context pack.

## Acceptance checks

A package creation change is valid when:

1. the Package and all bound Experiments appear in a verified state fold;
2. every Experiment has a complete four-field spec;
3. every bound Experiment keeps its accepted Scope id and has exactly one
   Package/local-id binding;
4. no dependency was invented;
5. evidence paths resolve below `.research/experiments/`;
6. package creation did not render or inspect HTML; and
7. a later renderer rebuild can reproduce the same human page hierarchy.
