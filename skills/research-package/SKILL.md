---
name: research-package
description: "Use when the user invokes /research-package or asks to create, initialize, draft, scaffold, or materially restructure a research package under research_html/packages, including materializing accepted Scope SSOT Directions, adding dashboard package entries, or large structural results.html edits."
argument-hint: "from-scope <direction-id> | manual <one-sentence package goal> [category=<lane>, scope=<pages>]"
allowed-tools: Bash(*), Read, Edit, Write, Glob, Grep
---

# Research Package

## Purpose

Create one concrete research package whose pages each own one decision and link to the others. The hierarchy is binding: every field has exactly one home page; downstream pages link, they do not re-list.

This skill is project-agnostic. The contract is identical for every project; project specifics live in the inventory plus per-package content.

## Authority

Authority order, highest first:
1. The user's invocation prompt and any explicit `--<flag>` overrides.
2. Trust rules `T1–T24` in `<root>/rules/trustworthy-research-rules.html` (per-stage page contracts `T18–T24`, plus T2/T8/T16/T17 cross-cutting).
3. Form rules `R1–R18` in `<root>/rules/html-rules.html`.
4. The executable controller in the toolbox `workflow.ts`.
5. [references/package-contract.md](references/package-contract.md) — the 12-concept table and per-page card contract.

## Output classification

Every text output this skill emits — intermediate progress lines, the final report, and HTML page content — classifies content by audience:

- **Both audiences** (default): facts, decisions, status, paths, and the concrete fields a human reader needs. Render inline.
- **Human-important only**: prose addressed to the user (questions, recommendations, summaries). Render inline.
- **Agent-important only**: continuity context, internal reasoning, file-map notes, "remember for next turn" pointers that the next agent benefits from but the user does not need on first read. Render collapsed by default:
  - **Chat output** (Claude Code UI): wrap the block in a markdown `>` blockquote; the UI collapses it by default.
  - **HTML pages** (this skill's templates): wrap the block in `<details data-audience="agent"><summary>agent context</summary>…</details>`; the `<details>` element renders closed by default so the human reader sees only the summary.

Both-audience content is written once, inline, without the blockquote or `<details>` wrapper. Do not use the blockquote form for emphasis or aesthetics — it carries audience meaning under this rule. The `data-audience="agent"` attribute and the `^> ` line prefix are stable anchors agents can grep for to recover their private notes.

## Pre-flight check

The dashboard must exist before any package is created. Run:

```bash
test -f <cwd>/research_html/index.html && test -f <cwd>/research_html/data/research-packages.js && echo ok
```

If the check fails, stop and tell the user: "The research dashboard is not set up at `<cwd>/research_html/`. Run `/research-dashboard` first, then re-run `/research-package`." Do not silently scaffold a missing dashboard from this skill — `/research-dashboard` is the right tool.

## Entry modes

Prefer the Scope path:

```text
/research-package from-scope <direction-id>
```

Use it whenever a package comes from a Project/Direction/Task Scope chain, including when the user asks
to convert a brainstormed Direction into a package. This mode reads committed Scope only. It never uses a
pending Triage proposal as package authority.

Use manual creation only for legacy or non-Scope packages:

```text
/research-package manual <package goal>
```

Manual creation must still fill the inventory contract, but it should not pretend to be Scope-backed.

## From accepted Scope Direction

When the user asks to generate a package from a Scope SSOT Direction, use the materializer only after both the Direction and its high-level validation Milestones are committed in the Scope SSOT:

First read the learning context gate so the package is not created without the current failed-method,
adopted-win, rule, and open-gap context:

```bash
python3 research_html/scripts/learning_context_gate.py --root research_html --json
```

If the gate fails, repair the learning surface before materializing the package.

First run the readiness diagnosis. It is read-only and gives the next owning skill when the package is
not ready:

```bash
python3 skills/research-package/scripts/create_from_scope.py \
  --check --json \
  --direction-id <direction-node-id> \
  --root research_html \
  --transitions outputs/_scope/transitions.jsonl
```

Only when `materializable` is `true`, write the package:

```bash
python3 skills/research-package/scripts/create_from_scope.py \
  --direction-id <direction-node-id> \
  --root research_html \
  --transitions outputs/_scope/transitions.jsonl
```

Hard rules:

- If `--check` reports `pending_direction`, `missing_direction`, `missing_tasks`, or `pending_tasks`,
  stop and hand off to the reported `nextSkill`.
- The materializer reads only committed `outputs/_scope/transitions.jsonl`; it never reads pending Triage proposals as package authority.
- The Direction node must exist, be `level == "direction"`, and be `status == "ACTIVE"`.
- At least one active child `level == "task"` milestone node must exist with the Direction as parent. Milestones are high-level validation objectives, not concrete package experiments.
- Duplicate package ids or existing package directories are rejected before write.
- The generated inventory entry carries `sourceDirection`, `sourceVersion`, `sourceChange`, and `sourceTasks` provenance.
- On success, the materializer immediately builds `outputs/<pkg>/context_pack.md` and
  `outputs/<pkg>/context_pack.json` from the committed Scope log and current learning stores. The package should not wait for the
  first `/research-run` tick to get its Agent context.

Default field mapping:

| Direction spec | Package field |
| --- | --- |
| `hypothesis` | `hypothesis`, `problem`, `objective`, `direction` |
| `metric` | `primaryMetric` |
| `success_gate` | `activeGate`, `primaryMetricVsGate` |
| `baselines` | `baseline` |

During materialization, the accepted Milestones are projected into initial package `experiments[]` rows. Each row is a concrete package-level execution task and carries `sourceTask` pointing back to the high-level SSOT Milestone. The package may later refine or split concrete experiments through `/research-op insert --target experiments-row`, but it must not invent new high-level validation goals without a Scope Milestone proposal.

## Required Details

Ask for any detail that cannot be inferred safely:

- package name and id (defaults to `YYYY-MM-DD-<slug>`)
- category: `in-progress`, `success`, or `fail` (brainstorm is not a package category — pre-package ideas live on the dashboard brainstorm lane via `/research-brainstorm`)
- category-scoped tag and `tagMeaning`
- problem, objective, motivation
- hypothesis (required)
- primary metric and budget gate (required)
- baseline (when a claim will be made)
- no-change boundary
- source path and artifact root
- first next action
- which stage pages to scaffold initially (`--scope`); see below

Ask in one short batch. If the user gave a broad idea only, ask for objective, category, metric gate, baseline, artifact root, and first next action.

## T2 inventory checklist (status strip + dashboard card)

Every package object on the dashboard surfaces these fields. If a field is unknown, pass the empty string and the renderer will paint literal `unmeasured`. Do **not** silently drop them. Required-by-`(category, status)` is enforced by `<root>/data/schema.js` and checked by `<root>/scripts/learnings_lint.py lint-status`.

| Inventory field | CLI flag | What it answers |
| --- | --- | --- |
| `status` | `--status` | The `(category, status)` cell. Legal values per category come from `data/schema.js`. in-progress: `CONTEXT_LOADED`/`IMPLEMENTING`/`IMPLEMENTATION_REVIEW`/`READY_TO_LAUNCH`/`EXPERIMENT_RUNNING`/`LIVE_ANALYSIS`/`RESULT_ANALYSIS`/`NEXT_ACTION_READY`/`BLOCKED`. success: `ADOPTED_UNCONFIRMED`/`ADOPTED`/`WIN_SUPERSEDED`. fail: `ARCHIVED`/`ARCHIVED_CONDITIONAL`. `--workflow-state` is kept as a deprecated alias. |
| `contributionSpineFlag` | `--contribution-spine-flag` | Which project-spine contribution this package touches (id from `RESEARCH_CONTRIBUTION_SPINE` in schema.js). |
| `direction` | `--direction` | One-sentence research direction (optional; create_from_scope sets it from the Direction hypothesis). |
| `activeGate` | `--active-gate` | The plan/spec gate that owns the next decision. Required for in-progress. |
| `primaryMetricVsGate` | `--primary-metric-vs-gate` | One-line "metric=value vs gate" string for the dashboard card. Required for in-progress. |
| `lastDecision` | `--last-decision` | One sentence per workflow ticket decision. |
| `lastDecisionEvidencePath` | `--last-decision-evidence-path` | Artifact path under runtime root that backs `lastDecision`. Verified by `lint-evidence`. |
| `nextRoute` | `--next-route` | One of `RUN_NEXT_EXPERIMENT`, `FIX_IMPLEMENTATION`, `REVISE_PLAN`, `TERMINATE`, `ASK_USER`. Required for in-progress. |
| `currentBlocker` | `--current-blocker` | One sentence; `unmeasured` if none. Required when status is `BLOCKED`. |
| `lastAction` | `--last-action` | The most recent command, edit, or observation (Resume Block field). |
| `openRuns` | `--open-runs` | tmux/session/job ids or `none` (Resume Block field). Required when status is `EXPERIMENT_RUNNING` or `LIVE_ANALYSIS`. |
| `lastUpdated` | `--last-updated` | ISO date; toggles `data-stale` on pages that predate it. |
| `experiments` | `--experiments <json>` at scaffold time, then `/research-op insert/update --target experiments-row` | Typed task spine array `[{id, label?, purpose, after, output, gate, status, measures, requiresCode, complex, runLink?, docsAnchor?}]` painted onto both `index.html#plan-status` (status chips by `renderPlanStatus()`) and `plan.html#experiments` (pipeline timeline by `renderPipelineTimeline()`). `measures` defaults true for new tasks; infra/setup tasks set `measures: false`. See [Pipeline timeline](#pipeline-timeline-binding) for caps. The scaffolders and research-op derive result slots, result-gate rows, change-card stubs, docs/pipeline blocks, and tracker to-dos from this spine. Update the matching entry's `status` whenever a phase opens/closes (same turn as the tracker row update). Allowed `status`: `pending`/`queued`/`running`/`completed`/`failed`/`skipped`/`blocked`. |
| `methodsTried` | (post-scaffold edit) | Array of `{method, hypothesis, gate, measured, verdict, evidencePath}` rows (verdict ∈ `{PASS, FAIL, INCONCLUSIVE}`). Appended over the life of the package per the Learnings Update Protocol below. Required for success / fail. |
| `terminationMessage` | (post-scaffold edit) | One sentence: why this package ended. Required for success / fail. |
| `adoptionPath` | (post-scaffold edit) | Where the win was adopted (e.g., `AGENTS.md#current-best`, `CLAUDE.md#current-best`, model code path, downstream package id). Required for success. |
| `supersededBy` / `promotedTo` / `reopenTrigger` | (post-scaffold edit) | Per-status cross-reference fields. See `data/schema.js`. |

## Scope-selection heuristic

Pick `--scope` from the prompt's stage:

| Prompt intent | Recommended scope |
| --- | --- |
| "Create a plan about ..." | `index,plan,tracker,docs,_agent` |
| "Track the implementation of ..." | `index,plan,implementation,tracker,docs,_agent` |
| "Run / launch / record live ..." | `index,plan,implementation,tracker,docs,_agent` (tracker owns launch readiness + per-run live cards) |
| "Record results / pick the next action" | `--scope all` |
| "Distill rules / write deep analysis of results" | add `analysis` (or use `--scope all`); content updates flow through `/research-analysis` thereafter |

Always-present pages (`index`, `tracker`, `docs`, `_agent`) are appended automatically.

## Single-home rule (binding)

Every field has exactly one home page; other pages link. This prevents overlap and reduces context pollution.

- Owned-files set lives only on `implementation.html`.
- No-change boundary as declared lives on `plan.html`; downstream affirmation is a boolean + commit hash + link, not a re-list of files.
- Hypothesis is canonical on `plan.html` and re-stated only on `implementation.html` and `results.html` (T8 transition pages).
- Per-validity exp counts live only on `results.html`.
- `analysis.html` is the single home for hand-curated rules and deep insights distilled from a package's results (see the [`research-analysis`](../research-analysis/SKILL.md) skill). It is scaffolded empty by `--scope analysis` (or `--scope all`); content updates flow through `/research-analysis` thereafter. `results.html` still owns the verdict-level summary; `analysis.html` owns the *why* and the generalizable lessons. Do not auto-populate it from results, tracker, or inventory.
- `tracker.html` is the single home for all execution state (folding the prior `launch.html` and `live.html`):
  - Pre-launch readiness facts (T21: GPU id, CUDA_VISIBLE_DEVICES, conda env, git commit, dataset path, expected runtime, dry-run, smoke) live only on `tracker.html` in the **Launch readiness** card.
  - No-change affirmation (T16: boolean + commit hash + link to `implementation.html#owned-files`) and the T1 launch user-ack slot live only on `tracker.html` in the **Launch readiness** card.
  - Per-run live state (last-log timestamp, missed-checks, retries, ETA, runtime root, recommended action with cited PLAN threshold, optional inline objective curve) lives only on `tracker.html` in the **Per-run cards** section.
  - The execution ledger tables **resource allocation** and **latest live check** (`data-table="resource-allocation"`, `data-table="live-check"`) live only on `tracker.html`. The **implementation review** is surfaced on `tracker.html` as a pointer card (`data-card="impl-review-pointer"`); its detail lives on `implementation.html`. Stage pages link to the tracker row.
- Per-phase launcher *commands* (the executable steps) are not contract content — they live next to the scripts they invoke (`packages/<id>/scripts/*.sh` or `packages/<id>/docs/launchers.md`). `tracker.html` rows link to the script, not duplicate its body.

## Pipeline timeline (binding)

The per-experiment specification has exactly one home: the pipeline timeline painted on `plan.html#experiments` from the inventory's `experiments[]` array. The same array also paints the status chips on `index.html#plan-status` &mdash; both surfaces are derived from inventory, so updating inventory is the only write path and both surfaces refresh together. This is the third arm of the single-home rule: phase-level *spec* lives in inventory; phase-level *execution state* still lives in tracker rows; phase-level *deep contract* (full input/output schemas, sentinel format, code anchors, commands) still lives in `docs/pipeline.html`. Hand-coded `<table data-table="experiments">` on `plan.html` is forbidden (single-home rule; not yet machine-checked by `learnings_lint.py`).

For brainstorm or single-phase packages where the timeline is over-engineered, leave `experiments[]` empty (or with one entry) and the timeline renders an empty-state. Never replace the painted slot with a static table.

### Per-node field contract

Each entry in `experiments[]` carries the following fields when the timeline is in use:

| # | Field | Source | Hard cap | Purpose |
| --- | --- | --- | --- | --- |
| 1 | `id` | inventory | matches `P\d+` or `P\d+[a-z]?` for fan-out shards | anchor + visual marker |
| 2 | `purpose` | inventory | **&le; 12 words, leading action verb** (`Audit`, `Generate`, `Train`, `Evaluate`, `Compare`, &hellip;) | one-line action statement |
| 3 | `after` | inventory | array of phase ids, `[]` for the first phase; every id resolves to another `experiments[].id` | dependency edges; the renderer draws fan-out / join when entries share an `after` value |
| 4 | `output` | inventory | exactly ONE key artifact (file path or named blob); no `\n`; full output list lives in `docs/pipeline.html` | what downstream phases consume |
| 5 | `gate` | inventory | exactly ONE measurable predicate; **no top-level `AND` / `OR`** (the lint flags compound predicates) | when this phase is DONE |
| 6 | `status` | inventory | one of `pending`/`queued`/`running`/`completed`/`failed`/`skipped`/`blocked` | painted as a chip on the node |
| 7 | `runLink?` | inventory | **dashboard-root-relative path starting with `packages/<pkg-id>/`** (e.g. `packages/2026-05-15-foo/tracker.html#resource-allocation`); the renderer prepends `RESEARCH_ROOT_PREFIX` so the link resolves both from the dashboard and from inside the package | execution surface |
| 8 | `docsAnchor?` | inventory; defaults to `docs/pipeline.html#<id_lowercase>` | **plan.html-relative** path (e.g. `docs/baseline-xpool.html`, `docs/baseline-xpool.html#feature-extraction`); must resolve to a file on disk under `packages/<pkg-id>/`. If the package uses per-phase doc pages instead of a single `docs/pipeline.html`, set `docsAnchor` explicitly per phase (lint rule `experiment-docs-anchor-missing` errors when the explicit path does not resolve; `experiment-docs-anchor-default-missing` warns when the default fires but `docs/pipeline.html` does not exist). | deep-dive link |

The hard caps are discipline levers: a phase whose `purpose` needs more than 12 words or whose `gate` is compound is almost always two phases hiding inside one. Split it. These caps and the `after` resolution are enforced by `learnings_lint.py alignment` for typed task-spine rows.

### Task-spine construction workflow

Every new package and every structural experiment change follows this order:

1. **Intake** — collect identity, category, hypothesis, metric gate, baseline, boundary, artifact root, and first action.
2. **Spine first** — author `experiments[]` before page content: `id`, action-verb `purpose` (&le;12 words), `after` DAG, one `output`, one `gate`, and `measures`/`requiresCode`/`complex`.
3. **Scaffold** — run the scaffolder with `--experiments <json>`; the task blocks are derived before content authoring.
4. **Verify** — run `python <root>/scripts/learnings_lint.py alignment --pkg <id>` and fix every error in the same turn.
5. **Execute** — status flips and task growth go through `/research-op`; a status flip touches the task's result, implementation, docs, tracker, and inventory thread in one turn.
6. **Terminate** — run terminal alignment before lane move: `python <root>/scripts/learnings_lint.py alignment --pkg <id> --terminal`, then the normal Stop Gate.

### Consequences for the deep contract

When the timeline is in use, `docs/pipeline.html` &sect;6 (per-phase spec) stops repeating `purpose` and `gate`. Each phase block opens with one backlink &mdash; e.g., "P0 &mdash; see <a href="../plan.html#experiments">plan.html#experiments</a> for purpose + gate" &mdash; and the rest of the block covers HOW only: full input/output schemas, sentinel format and content, code anchors (`file:function`), multi-GPU policy, resume pattern, error handling. Each `<h3>` in &sect;6 carries an `id="p0"`, `id="p1"`, &hellip; so the timeline's `docsAnchor` deep-link scrolls to the right block.

### Renderer + lint

- `renderPipelineTimeline()` in `assets/research.js` paints the timeline from `experiments[]` into the `[data-card="pipeline-timeline"] [data-field="pipeline-timeline-list"]` slot on `plan.html`.
- Each node includes task-thread chips linking to the owning tracker, result, implementation, and docs surfaces when the row declares those needs.
- CSS for the pipeline card lives under `.pipeline-card` in `assets/research.css`.
- `learnings_lint.py alignment` enforces:
  - `experiments[].purpose` word count &le; 12 (error if exceeded);
  - `experiments[].gate` has no top-level `AND` / `OR`, no semicolon-joined predicates, and fewer than two comparator clauses (error if compound);
  - `experiments[].after` is a list and every id resolves to another `experiments[].id` (error otherwise);
  - a tracker to-do item for every typed task;
  - for `measures: true`, one result-gate row and one predefined `data-table="result-slot-<id>"` slot;
  - for `requiresCode: true`, one implementation change card bound by `validating-exp`;
  - for `complex: true`, a resolving docs anchor;
  - reverse orphans and status contradictions across result rows and change cards.

Legacy rows with none of `measures`/`requiresCode`/`complex` skip the derived-block checks with an `alignment-flags-unset` warning; the field caps (purpose/gate/output/`after`) stay always-on for every row.

## ETA discipline (binding)

Do not pre-estimate run duration. `plan.html` rows, launcher manifests, allocation rows, and live-check rows record `est_time=unknown` until the run has executed at least 30 minutes of stable throughput; after that, derive ETA from observed throughput and update on every 10-minute report.

## Results page pattern (recommended)

When scaffolding or editing `results.html`, follow the recommended structure in [references/results-page-pattern.md](references/results-page-pattern.md). The pattern captures the section ordering (hypothesis → eval-banner → headline → result-gate → tracks → validity → footer), the per-Track module pattern with `<details>` collapse hierarchy (**all `<details>` blocks closed by default — never write `<details open>`**; ordering top-to-bottom: current-best comparison, multi-seed cross-tabs, ablations, superseded variants, diagnostic-only), the 2–4-card headline metric-strip pattern, eval-banner usage when a canonical-policy distinction exists, and the rule that result-gate rows are per-planned-experiment (P0, P1, …), not per-measurement (sweep cells / multi-seed validations / ablation cells live in track tables). The pattern is R13-compatible: it is a recommendation derived from the panda-scaleup canonical example, not a binding scaffold. Deviate when the package's shape calls for it.

## Docs/* page style (project-local override)

When the host project ships its own doc-template and doc-style-guide under `research_html/templates/`, prefer those over this skill's bundled minimal `templates/docs/source.html` for any new doc under `research_html/packages/<pkg-id>/docs/`. A host project that ships `research_html/templates/doc-template.html` + `doc-style-guide.html` is the canonical example:

- **Skeleton:** `research_html/templates/doc-template.html` — content-agnostic shell (masthead with eyebrow + h1 + lead + toolbar + `data-status-strip` + `data-package-nav`, footer `<time data-field="last-updated">`, three trailing `<script>` tags) plus one labelled demo of every block primitive (`pre.diagram`, `pre.code`, `.callout` + `.warn` + `.ok`, `table.data-table`, `span.pill-mono` + `.frozen`/`.trained`/`.kmeans`, `h2.stage-title` + `span.step-num`, `p.card-text.kv-mini`).
- **Style guide:** `research_html/templates/doc-style-guide.html` — when to reach for each primitive (rules + rendered examples + copy snippets). Re-read before authoring a new doc.
- **Exemplar:** a host-project-local doc such as `research_html/packages/<pkg-id>/docs/<pipeline>.html` shows a fully-fleshed-out doc under this style (numbered stages, appendices, footer time).

Hard rules: keep the shell verbatim (`data-status-strip`, `data-package-nav`, footer `<time>`, the three trailing `<script>` tags); do not invent new block classes; do not add page-local CSS beyond the primitive overrides at the top of the template; bump the footer date with a short scope phrase on every meaningful edit.

Section composition is content-agnostic: the template prescribes the shell and the primitives, not section count, section order, or section topics. A perf-fix doc can be one card; a full pipeline walk-through can be eight. Use only the primitives that earn their place.

When the host project ships no such templates, fall back to this skill's `templates/docs/source.html` (minimal shell only).

## Creation Workflow

The bundled script reads the stage templates from this skill's `templates/` directory (one per entry in its `STAGE_PAGES` map) and substitutes per-package fields. Invoke it as:

```bash
PACKAGE_SKILL=""
for dir in "$HOME/.codex/skills/research-package" "$HOME/.claude/skills/research-package"; do
  if [ -f "$dir/scripts/create_research_package.py" ]; then PACKAGE_SKILL="$dir"; break; fi
done
test -n "$PACKAGE_SKILL"
python "$PACKAGE_SKILL/scripts/create_research_package.py" \
  --root <cwd>/research_html \
  --id YYYY-MM-DD-slug \
  --name "Package Name" \
  --category in-progress \
  --tag "short tag" \
  --tag-meaning "Current status: ..." \
  --problem "..." \
  --objective "..." \
  --motivation "..." \
  --hypothesis "..." \
  --primary-metric "..." \
  --baseline "..." \
  --budget "..." \
  --no-change-boundary "..." \
  --next-action "..." \
  --status CONTEXT_LOADED \
  --contribution-spine-flag <id-from-schema.js> \
  --active-gate "..." \
  --next-route ASK_USER \
  --last-action "scaffolded package" \
  --open-runs "none" \
  --experiments '[{"id":"P0","purpose":"Verify baseline","after":[],"output":"outputs/P0/result.json","gate":"Recall@1 >= baseline","status":"queued","measures":true,"requiresCode":false,"complex":false}]' \
  --scope index,plan,results,tracker,docs,_agent
```

From an accepted Scope Direction, prefer the materializer instead of manually copying spec fields:

```bash
python3 skills/research-package/scripts/create_from_scope.py \
  --check --json \
  --direction-id dir/retrieval-v2 \
  --id 2026-06-03-retrieval-v2

python3 skills/research-package/scripts/create_from_scope.py \
  --direction-id dir/retrieval-v2 \
  --id 2026-06-03-retrieval-v2
```

After scaffolding, run:

```bash
python <root>/scripts/learnings_lint.py lint-status
python <root>/scripts/learnings_lint.py alignment --pkg <id>
```

It exits 0 if all required fields for `(category, status)` are present.

After scaffolding, patch package-specific details that the script could not know (see post-scaffold checklist below).

## Post-scaffold patch checklist

The scaffold writes generic templates. Patch these `unmeasured` slots when the prompt provides the value:

- `plan.html` &rarr; metric card subfields (`metric-formula`, `metric-dataset`, `metric-protocol`, `metric-dedup`, `metric-cutoff`); baseline subfields (`baseline-checkpoint`, `baseline-protocol`, `baseline-last-verified`); seed plan; plan-diff. The **Pipeline timeline** section under `[data-section="pipeline-timeline"]` is auto-painted from inventory `experiments[]` by `renderPipelineTimeline()` &mdash; do not hand-edit the painted slot and do not add a `<table data-table="experiments">` next to it; populate the inventory entry's `purpose`/`after`/`output`/`gate`/`status`/`runLink` fields instead. Brainstorm or single-phase packages leave `experiments[]` empty (or with one entry) and the timeline renders an empty-state. See [Pipeline timeline](#pipeline-timeline-binding) for the binding contract.
- `index.html` &rarr; Plan Status card placeholder is auto-painted from inventory `experiments[]` by `renderPlanStatus()`. Do not hand-edit the painted slot; edit the inventory entry instead.
- `implementation.html` &rarr; owned-files list; diff summary; one `data-card="change"` per algorithm change with `data-field="component"`, `data-field="code-anchor"` in `file:function` form, `data-field="expected-sign"`, `data-field="expected-magnitude"`, `data-field="validating-exp"`.
- `tracker.html` &rarr; Resume Block fields are auto-painted from inventory by `renderResumeBlock()`; you only need to update inventory. Append rows to the two execution ledger tables (`resource-allocation`, `live-check`) via the `data-table-body` selector (see [references/package-contract.md](references/package-contract.md)); the implementation-review pointer card links to `implementation.html`. Fill the **Launch readiness** card (T21 readiness fields, expected runtime, dry-run / smoke status, T16 no-change affirmation, T1 launch user-ack). Add one **Per-run card** per open experiment under the `[data-section="run-cards"]` host (T22 + T15: state, last-log, missed-checks, retries, ETA, runtime root, cited PLAN threshold, recommended action, optional inline objective SVG). The to-do list under `data-field="todo-list"` is strict: each `<li>` must wrap its content in `<label><input type="checkbox"> &hellip;</label>`; add the `checked` attribute when the item is done. Plain `<li>text</li>` is not permitted.
- `_agent/context.html` &rarr; canonical paths only; do not duplicate identity fields from `index.html`.

## Validation

- `node --check <cwd>/research_html/data/research-packages.js`
- `node --check <cwd>/research_html/assets/research.js`
- Open `<cwd>/research_html/index.html` from disk: the new package appears in the dashboard package grid; lane and route filters narrow it.
- Open `<cwd>/research_html/packages/<id>/index.html`: status strip, package nav, identity card, and page index render. Missing fields show `unmeasured`.
- Run the alignment lint, then use the greps below only for targeted debugging:
  ```bash
  python <cwd>/research_html/scripts/learnings_lint.py alignment --pkg <id>
  ```
- Grep that the execution ledger tables live only on `tracker.html`, and that implementation-review is a pointer card (not a table):
  ```bash
  grep -nE 'data-table="(resource-allocation|live-check)"' \
    <cwd>/research_html/packages/<id>/*.html
  # only tracker.html should match.
  grep -l 'impl-review-pointer' <cwd>/research_html/packages/<id>/tracker.html
  # tracker.html carries the implementation-review pointer card; its detail lives on `implementation.html`.
  ```
- Grep that no stage page links to the retired `launch.html` / `live.html`:
  ```bash
  grep -nE '(launch|live)\.html' <cwd>/research_html/packages/<id>/*.html || echo "clean"
  ```
- Grep that `plan.html` has the painted timeline slot and does NOT carry any static experiments table (single-home rule &mdash; the timeline is the only valid form):
  ```bash
  grep -nE 'data-section="pipeline-timeline"|data-table(-body)?="experiments"' \
    <cwd>/research_html/packages/<id>/plan.html
  # expect exactly one match for the pipeline-timeline slot and none for any data-table*="experiments".
  ```
- Grep that `docs/pipeline.html` does not re-state `<b>Gate:</b>` on every phase block (gate is owned by inventory and painted on the timeline):
  ```bash
  grep -nE '<b>Gate:</b>' <cwd>/research_html/packages/<id>/docs/pipeline.html || echo "clean"
  ```
- Grep that every &sect;6 phase `<h3>` carries an `id="p<N>"` anchor that the timeline's `docsAnchor` deep-link can target:
  ```bash
  grep -cE '<h3 id="p[0-9]+(?:[a-z])?">' <cwd>/research_html/packages/<id>/docs/pipeline.html
  # should equal the number of experiments[] entries on that package.
  ```
- Grep that the hypothesis is restated exactly on `implementation.html` and `results.html`:
  ```bash
  grep -nE 'data-hypothesis-restated' <cwd>/research_html/packages/<id>/*.html | wc -l
  ```

## Final response

State:

- package id and name
- dashboard lane
- tag and tag meaning
- scaffolded pages (`--scope` resolved)
- files created
- validation run
- unresolved placeholders or questions

Example:

```
Created package 2026-06-03-contrastive-recall (in-progress) on the in-progress lane.
Tag: baseline-sweep — "comparing 3 contrastive losses".
Pages: index, plan, tracker, docs, _agent (--scope index,plan,tracker,docs,_agent).
Files: 5 written under research_html/packages/2026-06-03-contrastive-recall/.
Validation: learnings_lint.py lint-status → exit 0.
Open question: baseline checkpoint path still unmeasured.
```

Apply the [Output classification](#output-classification) rule on the report — agent-only continuity notes go in a `>` blockquote so the user is not asked to read them.

## Fact Propagation Contract (binding when a run is live)

Fact propagation is owned by the `/research-op` skill, not this one. Every artifact that lands during a research run (checkpoint, candidate JSON, sentinel, phase marker, chain-done) is detected by `/research-op scan-events` and fanned out atomically by `/research-op event <name>` through Pattern B validation. The cursor advances on successful fan-out; manual `--bump` is no longer needed.

Per-package `scripts/propagate_facts.py` byte-copies are no longer shipped by this skill.

## Learnings Update Protocol (binding when a verdict lands)

`methodsTried[]`, `terminationMessage`, and `adoptionPath` on a package entry are the project-wide "what was tried" record consumed by `<root>/learnings.html`. They must be written under an event-trigger × lint-gate × atomic-turn protocol:

| Event | Trigger surface | User ack | Inventory fields written |
| --- | --- | --- | --- |
| **`VERDICT_FINALIZED`** | `results.html` result-gate row gains PASS/FAIL/INCONCLUSIVE AND artifacts verified | none | Append one `methodsTried[]` row |
| **`STATUS_CHANGED`** | tracker live-check, plan revision, blocker change | none | `status`, `activeGate`, `primaryMetricVsGate`, `currentBlocker`, `openRuns`, `lastAction`, `lastUpdated` |
| **`TERMINAL_TRANSITION`** | `tracker.html#chosen-route` → terminal lane move | **T1** | `category` (lane move), `status`, `terminationMessage`; freeze `methodsTried[]` |
| **`ADOPTION`** | `AGENTS.md` / `CLAUDE.md` "Current Best" edit, code merge into `models/` / `trainer/`, or downstream pkg cites the win | **T1** | `adoptionPath` |
| **`SUPERSESSION`** | Newer success pkg replaces an older one | **T1** | On the *old* pkg: `status = WIN_SUPERSEDED`, `supersededBy` |
| **`REOPEN`** | User states a fail pkg should be revisitable | **T1** | `status = ARCHIVED_CONDITIONAL`, `reopenTrigger` |

Each `methodsTried` row is exactly six fields, drawn from the witnessing `results.html` row:

```
{ method, hypothesis, gate, measured, verdict, evidencePath }
```

`verdict` ∈ `{PASS, FAIL, INCONCLUSIVE}`. `evidencePath` must resolve to a file or to a stable HTML anchor (`results.html#<exp-id>`). The dashboard-wide tool that drafts and validates these rows is `<root>/scripts/learnings_lint.py` (lives on the dashboard, not in each package). Subcommands:

```bash
python <root>/scripts/learnings_lint.py lint-status     # schema + cross-ref lint
python <root>/scripts/learnings_lint.py lint-evidence   # evidencePath resolution
python <root>/scripts/learnings_lint.py scan-events     # 3 draft writers (E1/E3/E4)
python <root>/scripts/learnings_lint.py draft-method <pkg-id> <anchor>
python <root>/scripts/learnings_lint.py draft-terminal <pkg-id>
python <root>/scripts/learnings_lint.py all
```

Per-turn closure when any event above fires: update the upstream witness (results.html / tracker.html#chosen-route), then the inventory entry in `data/research-packages.js`, then the tracker Resume Block `lastAction`, then run `learnings_lint.py all`. A non-empty report is a Stop-Gate violation.

`learnings.html` re-derives on load — do not edit it directly.

### Auto-applier (event manifests)

`<root>/scripts/propagate_apply.py` (shipped by the `research-dashboard` skill) is the deterministic executor for events `VERDICT_FINALIZED`, `TERMINAL_TRANSITION`, `ADOPTION`, `SUPERSESSION`, and `REOPEN`. A launcher (or the agent) writes a small JSON manifest under `outputs/<pkg-id>/manifests/` with one of these event keys: `VERDICT_FINALIZED` · `STATUS_CHANGED` (STATUS_CHANGED-style top-level status) · `ADOPTION` · `SUPERSESSION` · `REOPEN`. The applier reads every unapplied manifest, writes the deterministic surface edits, marks the manifest `.applied`, and is idempotent on re-run. See `research-dashboard/SKILL.md` § *Event-manifest applier* for the full schema.

For E2 (in-progress live update), `propagate_apply.py --auto-derive` scans every package on demand and fills **blank** `currentBlocker` / `nextRoute` fields based on `experiments[].status`. Non-blank fields stay untouched — they are treated as human-curated and require an explicit `state_derived` manifest to overwrite.

When wired to a Claude Code `Stop` hook (recipe at `research-dashboard/references/stop-fact-propagation-hook.md`), the applier + auto-derive + `learnings_lint.py all` chain runs on every turn end with no model tokens spent on the propagation step.

## Bundled resources

- `scripts/create_research_package.py` — generates a hierarchical package from this skill's templates and appends one inventory entry to the user's `data/research-packages.js`.
- `templates/` — the 10 `string.Template` HTML files. Eight are scaffolded stage pages (the `STAGE_PAGES` keys: `index`, `plan`, `implementation`, `results`, `analysis`, `tracker`, `docs/index`, `_agent/context`); `brainstorm.html` is a provenance-only template written by `create_from_scope.py` at conversion time and is not a `--scope` key; `docs/source.html` is a standalone fallback template for new per-source doc pages, not a `--scope` key. Tracker owns launch readiness + per-run live cards **and** the chosen-route panel; there is no longer a separate `launch.html`, `live.html`, or `next-action.html` template — the next-action decision is folded into `tracker.html#chosen-route`. The `analysis` template is the empty two-block scaffold (Rules + Insight) — its content discipline lives in the [`research-analysis`](../research-analysis/SKILL.md) skill.
- `references/package-contract.md` — the 12-concept table, single-home rule, append-row recipe, and the four `data-ack` transition slots.
- `references/results-page-pattern.md` — recommended structure for `results.html` derived from the panda-scaleup canonical example: section ordering (hypothesis → eval-banner → headline → result-gate → tracks → validity → footer), Track module pattern with `<details>` collapse hierarchy (**all `<details>` blocks closed by default — never `<details open>`**; order top-to-bottom: current-best, multi-seed, ablation, superseded, diagnostic-only), 2–4-card headline metric-strip pattern, and the rule that result-gate rows are per-planned-experiment (not per-measurement).
