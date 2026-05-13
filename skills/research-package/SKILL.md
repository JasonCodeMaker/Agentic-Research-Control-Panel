---
name: research-package
description: "Create a hierarchical research package under research_html/packages/<YYYY-MM-DD-slug>/ as a multi-page HTML surface (overview, plan, implementation, results, next-action, tracker, brainstorm) plus docs/ and _agent/. Use this skill whenever the user types /research-package, asks to create / initialize / draft / scaffold a research package, sets up a new research direction or experiment plan, or wants a new package on the dashboard for in-progress / brainstorm / success / fail work. Project-agnostic. Hard requirement: the dashboard at <cwd>/research_html/ must already exist — if it does not, run /research-dashboard first. Each page owns one decision; the binding single-home rule prevents overlap and context pollution. Tracker is the single home for execution state — launch readiness, resource allocation, per-run live cards, and the 10-minute live check all live on tracker.html (the prior launch.html / live.html pages are folded in)."
argument-hint: "<one-sentence description of the package goal, optionally followed by — category=<lane>, scope=<pages>>"
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
3. Form rules `R1–R17` in `<root>/rules/html-rules.html`.
4. The seven-step controller in the user's `WORKFLOW.md` if one exists at the repo root.
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

## Required Details

Ask for any detail that cannot be inferred safely:

- package name and id (defaults to `YYYY-MM-DD-<slug>`)
- category: `brainstorm`, `in-progress`, `success`, or `fail`
- category-scoped tag and `tagMeaning`
- problem, objective, motivation
- hypothesis (required for non-brainstorm; optional for brainstorm)
- primary metric and budget gate (required for non-brainstorm)
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
| `status` | `--status` | The `(category, status)` cell. Legal values per category come from `data/schema.js`. brainstorm: `EXPLORING`/`PILOT_READY`/`PROMOTED`/`ABANDONED`. in-progress: `CONTEXT_LOADED`/`IMPLEMENTING`/`IMPLEMENTATION_REVIEW`/`READY_TO_LAUNCH`/`EXPERIMENT_RUNNING`/`LIVE_ANALYSIS`/`RESULT_ANALYSIS`/`NEXT_ACTION_READY`/`BLOCKED`. success: `ADOPTED_PENDING_ACK`/`ADOPTED`/`SUPERSEDED`. fail: `ARCHIVED`/`ARCHIVED_REOPENABLE`. `--workflow-state` is kept as a deprecated alias. |
| `contributionSpineFlag` | `--contribution-spine-flag` | Which project-spine contribution this package touches (id from `RESEARCH_CONTRIBUTION_SPINE` in schema.js). |
| `direction` | `--direction` | One-sentence research direction. Required for brainstorm. |
| `activeGate` | `--active-gate` | The plan/spec gate that owns the next decision. Required for in-progress. |
| `primaryMetricVsGate` | `--primary-metric-vs-gate` | One-line "metric=value vs gate" string for the dashboard card. Required for in-progress. |
| `lastDecision` | `--last-decision` | One sentence per WORKFLOW.md "Decision" line. |
| `lastDecisionEvidencePath` | `--last-decision-evidence-path` | Artifact path under runtime root that backs `lastDecision`. Verified by `lint-evidence`. |
| `nextRoute` | `--next-route` | One of `run_next_experiment_from_step4`, `fix_implementation`, `revise_plan`, `archive_or_stop`, `ask_user`. Required for in-progress. |
| `currentBlocker` | `--current-blocker` | One sentence; `unmeasured` if none. Required when status is `BLOCKED`. |
| `lastAction` | `--last-action` | The most recent command, edit, or observation (Resume Block field). |
| `openRuns` | `--open-runs` | tmux/session/job ids or `none` (Resume Block field). Required when status is `EXPERIMENT_RUNNING` or `LIVE_ANALYSIS`. |
| `lastUpdated` | `--last-updated` | ISO date; toggles `data-stale` on pages that predate it. |
| `experiments` | (post-scaffold edit) | Array `[{id,label?,status,runLink?}]` painted onto `index.html#plan-status`. Update the matching entry's `status` whenever a phase opens/closes (same turn as the tracker row update). Allowed: `pending`/`queued`/`running`/`completed`/`failed`/`skipped`/`blocked`. |
| `methodsTried` | (post-scaffold edit) | Array of `{method, hypothesis, gate, measured, verdict, evidencePath}` rows (verdict ∈ `{pass, fail, inconclusive}`). Appended over the life of the package per the Learnings Update Protocol below. Required for success / fail / brainstorm-`ABANDONED`. |
| `terminationMessage` | (post-scaffold edit) | One sentence: why this package ended. Required for success / fail / brainstorm-`ABANDONED`. |
| `adoptionPath` | (post-scaffold edit) | Where the win was adopted (e.g., `CLAUDE.md#current-best`, model code path, downstream package id). Required for success. |
| `supersededBy` / `promotedTo` / `reopenTrigger` | (post-scaffold edit) | Per-status cross-reference fields. See `data/schema.js`. |

## Scope-selection heuristic

Pick `--scope` from the prompt's stage:

| Prompt intent | Recommended scope |
| --- | --- |
| "Brainstorm a direction ..." (category=brainstorm) | `index,docs,_agent` (brainstorm.html is auto-included) |
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
  - The three WORKFLOW.md ledger tables (implementation review, resource allocation, latest live check) live only on `tracker.html`. Stage pages link to the tracker row.
- Per-phase launcher *commands* (the executable steps) are not contract content — they live next to the scripts they invoke (`packages/<id>/scripts/*.sh` or `packages/<id>/docs/launchers.md`). `tracker.html` rows link to the script, not duplicate its body.

## ETA discipline (binding)

Do not pre-estimate run duration. `plan.html` rows, launcher manifests, allocation rows, and live-check rows record `est_time=unknown` until the run has executed at least 30 minutes of stable throughput; after that, derive ETA from observed throughput and update on every 10-minute report.

## Creation Workflow

The bundled script reads the 12 stage templates from this skill's `templates/` directory and substitutes per-package fields. Invoke it as:

```bash
python ~/.claude/skills/research-package/scripts/create_research_package.py \
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
  --next-route ask_user \
  --last-action "scaffolded package" \
  --open-runs "none" \
  --scope index,plan,tracker,docs,_agent
```

For a brainstorm package, also pass `--direction "<one-sentence direction>"` so the package is lint-clean at scaffold time. After scaffolding, run:

```bash
python <root>/scripts/learnings_lint.py lint-status
```

It exits 0 if all required fields for `(category, status)` are present.

After scaffolding, patch package-specific details that the script could not know (see post-scaffold checklist below).

## Post-scaffold patch checklist

The scaffold writes generic templates. Patch these `unmeasured` slots when the prompt provides the value:

- `plan.html` &rarr; metric card subfields (`metric-formula`, `metric-dataset`, `metric-protocol`, `metric-dedup`, `metric-cutoff`); baseline subfields (`baseline-checkpoint`, `baseline-protocol`, `baseline-last-verified`); seed plan; plan-diff; experiments-list spec rows (Exp ID, Purpose, Owner, Run link — no Status column).
- `index.html` &rarr; Plan Status card placeholder is auto-painted from inventory `experiments[]` by `renderPlanStatus()`. Do not hand-edit the painted slot; edit the inventory entry instead.
- `implementation.html` &rarr; owned-files list; diff summary; one `data-card="change"` per algorithm change with `data-field="component"`, `data-field="code-anchor"` in `file:function` form, `data-field="expected-sign"`, `data-field="expected-magnitude"`, `data-field="validating-exp"`.
- `tracker.html` &rarr; Resume Block fields are auto-painted from inventory by `renderResumeBlock()`; you only need to update inventory. Append rows to the three ledger tables via the `data-table-body` selector (see [references/package-contract.md](references/package-contract.md)). Fill the **Launch readiness** card (T21 readiness fields, expected runtime, dry-run / smoke status, T16 no-change affirmation, T1 launch user-ack). Add one **Per-run card** per open experiment under the `[data-section="run-cards"]` host (T22 + T15: state, last-log, missed-checks, retries, ETA, runtime root, cited PLAN threshold, recommended action, optional inline objective SVG). The to-do list under `data-field="todo-list"` is strict: each `<li>` must wrap its content in `<label><input type="checkbox"> &hellip;</label>`; add the `checked` attribute when the item is done. Plain `<li>text</li>` is not permitted.
- `_agent/context.html` &rarr; canonical paths only; do not duplicate identity fields from `index.html`.

## Validation

- `node --check <cwd>/research_html/data/research-packages.js`
- `node --check <cwd>/research_html/assets/research.js`
- Open `<cwd>/research_html/index.html` from disk: the new package appears in the dashboard package grid; lane and route filters narrow it.
- Open `<cwd>/research_html/packages/<id>/index.html`: status strip, package nav, identity card, and page index render. Missing fields show `unmeasured`.
- Grep that the three ledger tables exist only on `tracker.html` (and not on any sibling stage page):
  ```bash
  grep -nE 'data-table="(implementation-review|resource-allocation|live-check)"' \
    <cwd>/research_html/packages/<id>/*.html
  # only tracker.html should match.
  ```
- Grep that no stage page links to the retired `launch.html` / `live.html`:
  ```bash
  grep -nE '(launch|live)\.html' <cwd>/research_html/packages/<id>/*.html || echo "clean"
  ```
- Grep that `plan.html` does not carry a Status column or static `data-validity` chips in the experiments table (state moved to inventory `experiments[]`, painted on `index.html#plan-status`):
  ```bash
  grep -nE 'data-table="experiments".*<th>Status</th>|<tbody data-table-body="experiments">.*data-validity' \
    <cwd>/research_html/packages/<id>/plan.html || echo "clean"
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

Apply the [Output classification](#output-classification) rule on the report — agent-only continuity notes go in a `>` blockquote so the user is not asked to read them.

## Fact Propagation Contract (binding when a run is live)

Every artifact that lands during a research run (checkpoint, candidate JSON, sentinel, phase marker, chain-done) is a "locked fact" that the agent must propagate to every owning surface — `results.html`, `next-action.html`, registry status fields, tracker Resume Block — in the same turn the artifact is observed. The mechanical check is `scripts/propagate_facts.py`:

```bash
# every per-turn live cycle
python <package>/scripts/propagate_facts.py            # list newly-locked facts
# … agent applies the indicated updates to the listed surfaces …
python <package>/scripts/propagate_facts.py --bump     # advance the cursor
```

The cursor lives at `<runtime-root>/manifests/.propagation_cursor` (epoch float). An empty report = nothing to propagate; non-empty = the agent must update the listed surfaces *in the same turn* before scheduling the next wake. The Stop Gate requires an empty report.

The skill ships a single canonical implementation at `scripts/propagate_facts.py`; the scaffolder copies it into every new package's `scripts/` directory so every package inherits the same contract.

## Learnings Update Protocol (binding when a verdict lands)

`methodsTried[]`, `terminationMessage`, and `adoptionPath` on a package entry are the project-wide "what was tried" record consumed by `<root>/learnings.html`. They must be written under an event-trigger × lint-gate × atomic-turn protocol:

| Event | Trigger surface | User ack | Inventory fields written |
| --- | --- | --- | --- |
| **E1. Per-experiment verdict finalized** | `results.html` result-gate row gains pass/fail/inconclusive AND artifacts verified | none | Append one `methodsTried[]` row |
| **E2. In-progress live update** | tracker live-check, plan revision, blocker change | none | `status`, `activeGate`, `primaryMetricVsGate`, `currentBlocker`, `openRuns`, `lastAction`, `lastUpdated` |
| **E3. Terminal status transition** | `next-action.html` chosen-route → terminal lane move | **T1** | `category` (lane move), `status`, `terminationMessage`; freeze `methodsTried[]` |
| **E4. Adoption** | CLAUDE.md "Current Best" edit, code merge into `models/` / `trainer/`, or downstream pkg cites the win | **T1** | `adoptionPath` |
| **E5. Supersession** | Newer success pkg replaces an older one | **T1** | On the *old* pkg: `status = SUPERSEDED`, `supersededBy` |
| **E6. Reopen marked** | User states a fail pkg should be revisitable | **T1** | `status = ARCHIVED_REOPENABLE`, `reopenTrigger` |

Each `methodsTried` row is exactly six fields, drawn from the witnessing `results.html` row:

```
{ method, hypothesis, gate, measured, verdict, evidencePath }
```

`verdict` ∈ `{pass, fail, inconclusive}`. `evidencePath` must resolve to a file or to a stable HTML anchor (`results.html#<exp-id>`). The dashboard-wide tool that drafts and validates these rows is `<root>/scripts/learnings_lint.py` (lives on the dashboard, not in each package). Subcommands:

```bash
python <root>/scripts/learnings_lint.py lint-status     # schema + cross-ref lint
python <root>/scripts/learnings_lint.py lint-evidence   # evidencePath resolution
python <root>/scripts/learnings_lint.py scan-events     # 3 draft writers (E1/E3/E4)
python <root>/scripts/learnings_lint.py draft-method <pkg-id> <anchor>
python <root>/scripts/learnings_lint.py draft-terminal <pkg-id>
python <root>/scripts/learnings_lint.py all
```

Per-turn closure when any event above fires: update the upstream witness (results.html / next-action.html), then the inventory entry in `data/research-packages.js`, then the tracker Resume Block `lastAction`, then run `learnings_lint.py all`. A non-empty report is a Stop-Gate violation.

`learnings.html` re-derives on load — do not edit it directly.

## Bundled resources

- `scripts/create_research_package.py` — generates a hierarchical package from this skill's templates, appends one inventory entry to the user's `data/research-packages.js`, and copies `propagate_facts.py` into the new package's `scripts/` directory.
- `scripts/propagate_facts.py` — Fact Propagation Contract enforcer (see above). Read-only by default; `--bump` advances the cursor.
- `templates/` — the 11 `string.Template` HTML files (`index`, `plan`, `implementation`, `results`, `analysis`, `next-action`, `tracker`, `brainstorm`, `docs/index`, `docs/source`, `_agent/context`). Tracker owns launch readiness + per-run live cards; there is no longer a separate `launch.html` or `live.html` template. The `analysis` template is the empty two-block scaffold (Rules + Insight) — its content discipline lives in the [`research-analysis`](../research-analysis/SKILL.md) skill.
- `references/package-contract.md` — the 12-concept table, single-home rule, append-row recipe, and the four `data-ack` transition slots.
