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
- Per-run state (last-log, missed-checks, ETA, runtime root) is owned by
  `live.html`. The tracker's "Open Runs" carries an exp id + state + link.
- Per-validity exp counts are owned by `results.html`. The tracker shows a
  single open-run number and links to results.
- Source paths and artifact roots are owned by `index.html`.
- Implementation review, resource allocation, and latest live check tables are
  owned by `tracker.html`. Stage pages keep per-decision cards and link to the
  tracker row.
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
| 3 | Plan | `plan.html` | metric (name, formula, dataset, protocol, dedup, cutoff); baseline (source, checkpoint, protocol, last-verified date); budget gate; seed plan; experiments list; no-change boundary as declared; one-sentence diff vs prior plan | T9, T11, T16, T19 |
| 4 | Implementation changes | `implementation.html` | owned-files set; diff summary; change cards (T14: `file:function`, expected sign, magnitude band, validating exps); reviewer verdicts; integration verdict; adjudication | T14, T20 |
| 5 | Launch readiness | `launch.html` | GPU id, CUDA_VISIBLE_DEVICES, conda env, git commit, dataset path (each verified); expected runtime; dry-run + smoke status | T21 |
| 6 | Live monitoring | `live.html` | per open exp: state, last-log timestamp, missed-checks, retries, ETA, runtime root, inline objective curve (SVG), recommended live action with cited threshold | T15, T22, R3 |
| 7 | Results + analysis | `results.html` | result gate table; per-exp result cards with validity, baseline reference, plan gate, observed metric paired with artifact path + last-modified + checkpoint + git commit, supported / unsupported claims, protocol-match verdict; per-validity counts (chips, never aggregated); inline visualizations | T5, T9, T10, T13, T23, R3, R16 |
| 8 | Next action | `next-action.html` | chosen route from the allowed set; considered-and-rejected routes table with one-sentence reason each; cited evidence path | T24 |
| 9 | Tracker (execution ledger) | `tracker.html` | Resume Block (the seven WORKFLOW.md fields); implementation review table; resource allocation table; latest live check table; cross-stage to-do checklist (strict checkbox form) with links | T17, WORKFLOW.md "Tracker Hygiene" + Required Tables |
| 10 | Source docs | `docs/index.html` + `docs/<slug>.html` | one HTML per source (method-design, metric-contract, dataset-contract, runtime-contract, code-anchors, audits, reviews, references); each carries last-updated and one-line summary on the index | R8, R3, T17 |
| 11 | Continuity pointer (slim) | `_agent/context.html` | canonical source path, canonical runtime root, minimum context loading order, verification rules before result edits. **No fields duplicated from `index.html`**; references identity by `data-*` selectors | R6, T7 |
| 12 | Brainstorm-only fields | `brainstorm.html` (only when `category="brainstorm"`) | one-sentence direction; contribution-spine flag (preserves / changes); resolved citations; fail-history flag for prior packages with the same direction | T18 |

## Cross-cutting elements (precise scoping)

- **Status strip** (`<header data-status-strip>`): the six T2 fields, painted
  on every stage page from inventory. Missing values render literal
  `unmeasured`. (T2, T5)
- **Package nav** (`<nav data-package-nav>`): sticky on desktop; pages not
  present in `pages` render as disabled spans. (R1, R8)
- **Hypothesis re-statement**: only on `implementation.html` and `results.html`.
  String-equal vs canonical with `data-hypothesis-restated`. (T8)
- **No-change affirmation**: small card on `launch.html`, `live.html`,
  `results.html`, `next-action.html` with `affirmed` + `commit-hash` + link to
  `implementation.html#owned-files`. Never re-list the file set. (T16)
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
- `workflowState`, `activeGate`, `primaryMetricVsGate`, `lastDecision`,
  `lastDecisionEvidencePath`, `nextRoute`, `currentBlocker` &mdash; the six T2
  fields plus an evidence-path hint.
- `lastAction`, `openRuns` &mdash; WORKFLOW.md Resume Block fields, painted
  by `renderResumeBlock()` into `tracker.html`.
- `lastUpdated` &mdash; ISO date; toggles `data-stale` on pages that predate it.
- `pages` &mdash; array of stage-page slugs actually present on disk. Drives
  the disabled state in the package nav.

All new fields are optional; missing values render literal `unmeasured`.

## Resume Block painter (single source of truth)

`renderResumeBlock()` in `assets/research.js` paints the `<article
data-card="resume-block">` on `tracker.html` from the inventory. Updating the
inventory's `workflowState`, `lastAction`, `openRuns`, and `currentBlocker`
fields is the **only** write path required to keep the Resume Block fresh;
the static HTML acts as a fallback skeleton. Do not hand-edit the painted
slots in `tracker.html` — write inventory instead.

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
| Experiments list (5 cols) | `plan.html` | `[data-table-body="experiments"]` |
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
| Move to `EXPERIMENT_RUNNING` | `launch.html` no-change-affirmation | `experiment-running` |
| Promote a result to verdict `pass` | `results.html` result-gate `<tr>` | `result-pass` |
| Move package into `success` / `fail` / `STOPPED` | `next-action.html` chosen-route | `lane-transition` |

The agent must write the user's ack token (e.g. timestamp + initials) into the
`data-field="user-ack"` slot before recording the transition in the inventory
or moving the package between dashboard lanes.

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
