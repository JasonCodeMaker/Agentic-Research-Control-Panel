---
name: research-package
description: "Create a hierarchical research package under research_html/packages/<YYYY-MM-DD-slug>/ as a multi-page HTML surface (overview, plan, implementation, launch, live, results, next-action, tracker, brainstorm) plus docs/ and _agent/. Use this skill whenever the user types /research-package, asks to create / initialize / draft / scaffold a research package, sets up a new research direction or experiment plan, or wants a new package on the dashboard for in-progress / brainstorm / success / fail work. Project-agnostic. Hard requirement: the dashboard at <cwd>/research_html/ must already exist — if it does not, run /research-dashboard first. Each page owns one decision; the binding single-home rule prevents overlap and context pollution."
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

Every package object on the dashboard surfaces these fields. If a field is unknown, pass the empty string and the renderer will paint literal `unmeasured`. Do **not** silently drop them.

| Inventory field | CLI flag | What it answers |
| --- | --- | --- |
| `workflowState` | `--workflow-state` | One of WORKFLOW.md states (`CONTEXT_LOADED`, `IMPLEMENTING`, `READY_TO_LAUNCH`, `EXPERIMENT_RUNNING`, `LIVE_ANALYSIS`, `RESULT_ANALYSIS`, `NEXT_ACTION_READY`, `BLOCKED`, `STOPPED`). |
| `activeGate` | `--active-gate` | The plan/spec gate that owns the next decision. |
| `primaryMetricVsGate` | `--primary-metric-vs-gate` | One-line "metric=value vs gate" string for the dashboard card. |
| `lastDecision` | `--last-decision` | One sentence per WORKFLOW.md "Decision" line. |
| `lastDecisionEvidencePath` | `--last-decision-evidence-path` | Artifact path under runtime root that backs `lastDecision`. |
| `nextRoute` | `--next-route` | One of `run_next_experiment_from_step4`, `fix_implementation`, `revise_plan`, `archive_or_stop`, `ask_user`. |
| `currentBlocker` | `--current-blocker` | One sentence; `unmeasured` if none. |
| `lastAction` | `--last-action` | The most recent command, edit, or observation (Resume Block field). |
| `openRuns` | `--open-runs` | tmux/session/job ids or `none` (Resume Block field). |
| `lastUpdated` | `--last-updated` | ISO date; toggles `data-stale` on pages that predate it. |

## Scope-selection heuristic

Pick `--scope` from the prompt's stage:

| Prompt intent | Recommended scope |
| --- | --- |
| "Brainstorm a direction ..." (category=brainstorm) | `index,docs,_agent` (brainstorm.html is auto-included) |
| "Create a plan about ..." | `index,plan,tracker,docs,_agent` |
| "Track the implementation of ..." | `index,plan,implementation,tracker,docs,_agent` |
| "Run / launch / record live ..." | `index,plan,implementation,launch,live,tracker,docs,_agent` |
| "Record results / pick the next action" | `--scope all` |

Always-present pages (`index`, `tracker`, `docs`, `_agent`) are appended automatically.

## Single-home rule (binding)

Every field has exactly one home page; other pages link. This prevents overlap and reduces context pollution.

- Owned-files set lives only on `implementation.html`.
- No-change boundary as declared lives on `plan.html`; downstream affirmation is a boolean + commit hash + link, not a re-list of files.
- Hypothesis is canonical on `plan.html` and re-stated only on `implementation.html` and `results.html` (T8 transition pages).
- Per-run state (last-log, missed-checks, ETA) lives only on `live.html`.
- Per-validity exp counts live only on `results.html`.
- The three WORKFLOW.md ledger tables (implementation review, resource allocation, latest live check) live only on `tracker.html`. Stage pages link to the tracker row.

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
  --workflow-state CONTEXT_LOADED \
  --active-gate "..." \
  --next-route ask_user \
  --last-action "scaffolded package" \
  --open-runs "none" \
  --scope index,plan,tracker,docs,_agent
```

After scaffolding, patch package-specific details that the script could not know (see post-scaffold checklist below).

## Post-scaffold patch checklist

The scaffold writes generic templates. Patch these `unmeasured` slots when the prompt provides the value:

- `plan.html` &rarr; metric card subfields (`metric-formula`, `metric-dataset`, `metric-protocol`, `metric-dedup`, `metric-cutoff`); baseline subfields (`baseline-checkpoint`, `baseline-protocol`, `baseline-last-verified`); seed plan; plan-diff; experiments-list rows.
- `implementation.html` &rarr; owned-files list; diff summary; one `data-card="change"` per algorithm change with `data-field="component"`, `data-field="code-anchor"` in `file:function` form, `data-field="expected-sign"`, `data-field="expected-magnitude"`, `data-field="validating-exp"`.
- `launch.html` &rarr; the six T21 readiness fields; expected runtime; dry-run / smoke status.
- `tracker.html` &rarr; Resume Block fields are auto-painted from inventory by `renderResumeBlock()`; you only need to update inventory. Append rows to the three ledger tables via the `data-table-body` selector (see [references/package-contract.md](references/package-contract.md)). The to-do list under `data-field="todo-list"` is strict: each `<li>` must wrap its content in `<label><input type="checkbox"> &hellip;</label>`; add the `checked` attribute when the item is done. Plain `<li>text</li>` is not permitted.
- `_agent/context.html` &rarr; canonical paths only; do not duplicate identity fields from `index.html`.

## Validation

- `node --check <cwd>/research_html/data/research-packages.js`
- `node --check <cwd>/research_html/assets/research.js`
- Open `<cwd>/research_html/index.html` from disk: the new package appears in the dashboard package grid; lane and route filters narrow it.
- Open `<cwd>/research_html/packages/<id>/index.html`: status strip, package nav, identity card, and page index render. Missing fields show `unmeasured`.
- Grep that the three ledger tables exist only on `tracker.html`:
  ```bash
  grep -nE 'data-table="(implementation-review|resource-allocation|live-check)"' \
    <cwd>/research_html/packages/<id>/{tracker,implementation,launch,live}.html
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

## Bundled resources

- `scripts/create_research_package.py` — generates a hierarchical package from this skill's templates and appends one inventory entry to the user's `data/research-packages.js`.
- `templates/` — the 12 `string.Template` HTML files (`index`, `plan`, `implementation`, `launch`, `live`, `results`, `next-action`, `tracker`, `brainstorm`, `docs/index`, `docs/source`, `_agent/context`).
- `references/package-contract.md` — the 12-concept table, single-home rule, append-row recipe, and the four `data-ack` transition slots.
