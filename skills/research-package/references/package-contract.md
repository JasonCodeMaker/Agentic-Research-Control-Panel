# Research Package Contract

A research package is a hierarchical, link-driven HTML surface. Each page
contains only highly relevant content for one decision; pages link to each
other so an agent opens exactly what the next decision needs (context-pollution
control). Trust rules `T1-T24` in `rules/trustworthy-research-rules.html` and
the seven-step controller in `WORKFLOW.md` are binding for every package page.
HTML form rules `R1-R17` in `rules/html-rules.html` apply to every file.

## Single-home rule

Every field has exactly one home page. Other pages link to it; they never
re-list it.

- Owned-files set is owned by `implementation.html`.
- No-change boundary as declared is owned by `plan.html`; downstream pages
  carry a boolean + commit hash + link to `implementation.html#owned-files`.
- Hypothesis is canonical on `plan.html`; re-stated only on
  `implementation.html` and `results.html` (T8 transition scoping).
- Per-validity exp counts are owned by `results.html`. The tracker shows a
  single open-run number and links to results.
- Source paths and artifact roots are owned by `index.html`.
- `tracker.html` is the single home for execution state (the prior
  `launch.html` and `live.html` pages have been folded in):
  - Implementation review, resource allocation, and latest live check tables.
  - **Launch readiness** card: T21 readiness fields (GPU id,
    `CUDA_VISIBLE_DEVICES`, conda env, git commit, dataset path, expected
    runtime, dry-run, smoke); T16 no-change affirmation (boolean + commit hash
    + link to `implementation.html#owned-files`); T1 launch user-ack slot.
  - **Per-run cards** (one per open experiment): T22 per-run state (last-log,
    missed-checks, retries, ETA, runtime root), recommended action with the
    cited PLAN threshold, optional inline objective SVG (T15).
  - Per-phase launcher commands themselves are not contract content — they
    live next to their scripts in `packages/<id>/scripts/*.sh` (and an
    optional `docs/launchers.md` runbook). Tracker rows link to the script.
- Result gate table is owned by `results.html`.
- Considered routes table is owned by `next-action.html`.

## To-do checklist (strict format)

The cross-stage to-do list on `tracker.html` must render every item as a real,
clickable checkbox. The `<ul>` carries `class="todo-checklist"
data-field="todo-list"`, and each `<li>` wraps its full content in a
`<label>` so the whole row toggles the box:

```html
<ul class="todo-checklist" data-field="todo-list">
  <li><label><input type="checkbox" checked> Done item &mdash; <a href="implementation.html#changes">link</a></label></li>
  <li><label><input type="checkbox"> Open item &mdash; <a href="plan.html#experiments">link</a></label></li>
</ul>
```

Rules:

- Every `<li>` must contain exactly one `<label>` wrapping exactly one
  `<input type="checkbox">` plus the item text.
- Add the `checked` attribute (and only that attribute) when the item is
  done; remove it when the item is reopened.
- Do not nest sub-lists inside a `<li>`; split into separate items instead,
  so each owns one box.
- Plain `<li>text</li>` items are not permitted on `tracker.html`.

## 12 concepts

| # | Concept | Home page | Fields owned | Rule citations |
| --- | --- | --- | --- | --- |
| 1 | Identity | `index.html` | problem, objective, motivation, source path, artifact root, package id, summary line of the primary metric (link to `plan.html` for the full card) | T2, README |
| 2 | Hypothesis | `plan.html` | falsifiable hypothesis text (canonical) | T8, T19 |
| 3 | Plan | `plan.html` | metric (name, formula, dataset, protocol, dedup, cutoff); baseline (source, checkpoint, protocol, last-verified date); budget gate; seed plan; **experiments-list spec rows (Exp ID, Purpose, Owner, Run link — no Status column; per-row execution state lives on tracker resource-allocation rows and is painted onto `index.html#plan-status` from inventory)**; no-change boundary as declared; one-sentence diff vs prior plan | T9, T11, T16, T19 |
| 4 | Implementation changes | `implementation.html` | owned-files set; diff summary; change cards (T14: `file:function`, expected sign, magnitude band, validating exps); reviewer verdicts; integration verdict; adjudication | T14, T20 |
| 5 | Results + analysis | `results.html` | result gate table; per-exp result cards with validity, baseline reference, plan gate, observed metric paired with artifact path + last-modified + checkpoint + git commit, supported / unsupported claims, protocol-match verdict; per-validity counts (chips, never aggregated); inline visualizations | T5, T9, T10, T13, T23, R3, R16 |
| 6 | Next action | `next-action.html` | chosen route from the allowed set; considered-and-rejected routes table with one-sentence reason each; cited evidence path | T24 |
| 7 | Tracker (execution state, single home) | `tracker.html` | Resume Block (the seven WORKFLOW.md fields); cross-stage to-do checklist (strict checkbox form) with links; implementation review table; resource allocation table; latest live check table; **Launch readiness card** (T21 readiness fields, expected runtime, dry-run + smoke status, T16 no-change affirmation, T1 launch user-ack); **Per-run cards** section (per open exp: state, last-log, missed-checks, retries, ETA, runtime root, cited PLAN threshold, recommended action, optional inline objective SVG) | T15, T17, T21, T22, R3, WORKFLOW.md "Tracker Hygiene" + Required Tables |
| 8 | Source docs | `docs/index.html` + `docs/<slug>.html` | one HTML per source (method-design, metric-contract, dataset-contract, runtime-contract, code-anchors, audits, reviews, references); each carries last-updated and one-line summary on the index. Per-phase launcher commands (when documented in HTML rather than inline in scripts) live in `docs/launchers.md`. | R8, R3, T17 |
| 9 | Continuity pointer (slim) | `_agent/context.html` | canonical source path, canonical runtime root, minimum context loading order, verification rules before result edits. **No fields duplicated from `index.html`**; references identity by `data-*` selectors | R6, T7 |
| 10 | Brainstorm-only fields | `brainstorm.html` (only when `category="brainstorm"`) | one-sentence direction; contribution-spine flag (preserves / changes); resolved citations; fail-history flag for prior packages with the same direction | T18 |

## Cross-cutting elements (precise scoping)

- **Status strip** (`<header data-status-strip>`): the six T2 fields, painted
  on every stage page from inventory. Missing values render literal
  `unmeasured`. (T2, T5)
- **Package nav** (`<nav data-package-nav>`): sticky on desktop; pages not
  present in `pages` render as disabled spans. (R1, R8)
- **Hypothesis re-statement**: only on `implementation.html` and `results.html`.
  String-equal vs canonical with `data-hypothesis-restated`. (T8)
- **No-change affirmation**: small card on `tracker.html` (inside the Launch
  readiness card), `results.html`, and `next-action.html` with `affirmed` +
  `commit-hash` + link to `implementation.html#owned-files`. Never re-list the
  file set. (T16)
- **Last-updated + data-stale**: each page carries a `<time>` with the
  page's timestamp; `<html data-stale="true">` toggles when the page predates
  inventory's `lastUpdated`. (T17)
- **Verified vs recalled**: every fact-bearing element carries
  `data-verification`. (T6)
- **Validity chips**: `data-validity` chips on `results.html` only; never
  aggregated across classes. (R16, T10)

## Required initial files

When a package is first scaffolded, these are always emitted:

- `packages/<id>/index.html`
- `packages/<id>/tracker.html`
- `packages/<id>/docs/index.html`
- `packages/<id>/_agent/context.html`
- one inventory object in `data/research-packages.js`

Other stage pages are emitted via the scaffold script's `--scope` flag when
the package reaches that stage. Do not over-scaffold.

## Inventory schema (additive)

The inventory object accepts these additional fields beyond the original
package contract:

- `hypothesis` &mdash; canonical hypothesis text.
- `noChangeBoundary` &mdash; one-sentence boundary reference.
- `experiments` &mdash; ordered array `[{ id, label?, status, runLink? }, …]`. Painted onto `index.html#plan-status` by `renderPlanStatus()`. Allowed `status` values: `pending`, `queued`, `running`, `completed`, `failed`, `skipped`, `blocked`. The painter is the only read path; inventory is the only write path. Stale plan-status rows are a workflow violation if a tracker resource-allocation row reports a different status.
- `workflowState`, `activeGate`, `primaryMetricVsGate`, `lastDecision`,
  `lastDecisionEvidencePath`, `nextRoute`, `currentBlocker` &mdash; the six T2
  fields plus an evidence-path hint.
- `lastAction`, `openRuns` &mdash; WORKFLOW.md Resume Block fields, painted
  by `renderResumeBlock()` into `tracker.html`.
- `lastUpdated` &mdash; ISO date; toggles `data-stale` on pages that predate it.
- `pages` &mdash; array of stage-page slugs actually present on disk. Drives
  the disabled state in the package nav.
- `terminationMessage` &mdash; one short paragraph (1-3 sentences) explaining
  why the package ended. **Required** when `category` is `fail` or `success`;
  optional otherwise. Surfaced on the dashboard card as a `[FAILED]` /
  `[SUCCESS]` banner plus an inline "Termination" block by
  `packageCardHtml()` in `assets/research.js`.
- `methodsTried` &mdash; one short paragraph (1-3 sentences) naming the
  approaches the package attempted. **Required** when `category` is `fail`
  or `success`; optional otherwise. Surfaced on the dashboard card as an
  inline "Methods tried" block, so future packages can pick up context
  without re-reading every stage page.
- `reopenable` &mdash; boolean (default `false`). Set to `true` on a
  terminated card when the package's outputs (reusable infra, calibrated
  artifacts, distilled checkpoints, logged traces) remain useful for future
  work even though the method itself was rejected or superseded. Renders a
  "&#8631; Available for reopen" badge next to the route chip on the
  dashboard card. Meaningful only when the card is terminated.
- `reopenNote` &mdash; one short sentence describing what is reusable and
  under what condition reopening makes sense. Becomes the hover tooltip on
  the reopen badge. Optional; included only when `reopenable === true`.

All new fields are optional; missing values render literal `unmeasured`.

## Resume Block painter (single source of truth)

`renderResumeBlock()` in `assets/research.js` paints the `<article
data-card="resume-block">` on `tracker.html` from the inventory. Updating the
inventory's `workflowState`, `lastAction`, `openRuns`, and `currentBlocker`
fields is the **only** write path required to keep the Resume Block fresh;
the static HTML acts as a fallback skeleton. Do not hand-edit the painted
slots in `tracker.html` — write inventory instead.

`renderPlanStatus()` paints the `<article data-card="plan-status">` on
`index.html` from the inventory's `experiments[]` array. Each closed phase
must update the matching `experiments[i].status` in the inventory (one of
`pending`/`queued`/`running`/`completed`/`failed`/`skipped`/`blocked`) so
the Overview surface stays in sync with the tracker resource-allocation
row. Do not hand-edit the painted slot — write inventory instead.

Static slots in the Resume Block kv-grid that are **not** auto-painted (they
remain author-controlled): `Active plan` link, `Next action` link,
`Runtime root` code block. These are navigation, not state.

## Append-row recipe for ledger tables

Each WORKFLOW.md ledger table on the package surface exposes a stable
`data-table-body` selector inside its `<tbody>`. Tables and selectors:

| Table | Page | Selector |
| --- | --- | --- |
| Implementation review (15 cols) | `tracker.html` | `[data-table-body="implementation-review"]` |
| Resource allocation (14 cols) | `tracker.html` | `[data-table-body="resource-allocation"]` |
| Latest live check (12 cols) | `tracker.html` | `[data-table-body="live-check"]` |
| Result gate (10 cols) | `results.html` | `[data-table-body="result-gate"]` |
| Experiments list (4 cols, spec only) | `plan.html` | `[data-table-body="experiments"]` |
| Considered routes (4 cols) | `next-action.html` | `[data-table-body="considered-routes"]` |

Recipe for appending one row (any agent, any tool):

1. Read the page; locate the `<tbody data-table-body="...">` element.
2. Match the column count from the table header above.
3. Insert one `<tr>` immediately before `</tbody>`. Use the existing
   placeholder `<tr>` as a per-column field shape; replace `unmeasured` with
   the new value where applicable.
4. Each value-bearing `<td>` must carry a `data-field`, `data-validity`,
   `data-route`, `data-decision`, or `data-artifact` attribute consistent
   with the column.
5. For result-gate rows, the `<tr>` carries `data-ack="result-pass"
   data-ack-value=""`. Do not promote the verdict to `pass` until
   `data-ack-value` records a user ack token (T1).

After appending, the validity-class chip counts on `results.html` are
recomputed automatically by `renderValidityCounts()` on next page load.

## User-ack slots (T1)

Consequential transitions require a recorded user ack on the surface. Each
transition lives on a card with `data-ack="<transition>"` and a sibling
`data-field="user-ack"` slot:

| Transition | Card | `data-ack` value |
| --- | --- | --- |
| Move to `READY_TO_LAUNCH` | `implementation.html` adjudication | `ready-to-launch` |
| Move to `EXPERIMENT_RUNNING` | `tracker.html` Launch-readiness no-change-affirmation | `experiment-running` |
| Promote a result to verdict `pass` | `results.html` result-gate `<tr>` | `result-pass` |
| Move package into `success` / `fail` / `STOPPED` | `next-action.html` chosen-route | `lane-transition` |

The agent must write the user's ack token (e.g. timestamp + initials) into the
`data-field="user-ack"` slot before recording the transition in the inventory
or moving the package between dashboard lanes.

When recording the `lane-transition` ack (move into `success` / `fail` /
`STOPPED`), the agent must update the inventory in the same turn:

1. Flip `category` to `fail` or `success`.
2. Flip `nextRoute` from `archive_or_stop` to the matching terminal value:
   `archived` (fail lane) or `adopted` (success lane).
3. Populate `terminationMessage` and `methodsTried`.
4. Set `reopenable` (boolean) and, if `true`, write a one-sentence
   `reopenNote`.

A fail/success card missing the terminal `nextRoute`, `terminationMessage`,
or `methodsTried` is a contract violation. `reopenable=false` (or omitted)
is fine when nothing is reusable; `reopenable=true` without a `reopenNote`
is permitted but discouraged.

## Output classification (mirrored from SKILL.md)

The full rule lives in `SKILL.md` under [Output classification](../SKILL.md).
One-line summary for agents reading this contract first:

- **Agent-important only** chat output &rarr; wrap in a markdown `>`
  blockquote (UI collapses by default).
- **Agent-important only** HTML content &rarr; wrap in
  `<details data-audience="agent"><summary>agent context</summary>...</details>`
  (browser collapses by default).
- **Both-audience** content (the common case) renders inline without any
  wrapper.

`data-audience="agent"` extends the R6 stable-anchor taxonomy &mdash; agents
can grep for it to recover their private notes. Form rule R18 in
`rules/html-rules.html` is the binding HTML form of this rule.

## Final response

State:

- package id and name
- dashboard lane
- tag and tag meaning
- scaffolded pages (`--scope` resolved)
- files created
- validation run
- unresolved placeholders or questions
