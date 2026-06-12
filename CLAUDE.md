# CLAUDE.md — Trustworthy Research Pipeline

This file is the agent operating context for any project that adopts the Trustworthy Research Pipeline. It is intentionally project-agnostic. A consuming project copies this file into its repo root and **prepends** project-specific sections (project name, motivation, optimization objective, contribution spine, current best, dataset / budget gates) above the protocols below. The protocols themselves are universal — do not edit them per project.

## What this pipeline produces

A trustworthy research record where every claim is gated by an explicit metric, every metric is backed by a verified artifact, every direction has one declared next route, and every adopted win or archived failure leaves a structured `methodsTried` trace the next session can learn from. The skills bundled with this repo install the HTML surfaces, Scope/Triage gates, orchestration, and mutation tooling that enforce this. `workflow.ts` is the executable package controller the agent follows inside any package.

`research_html/` is the shared context surface, not the authority by itself. For research-affecting tasks,
load the narrow owning layer: `outputs/_scope/transitions.jsonl` for intent, package pages for
plan/tracker/result witnesses, `outputs/<pkg>/` plus live process state for measurements, and
`research_html/data/research-packages.js` for dashboard index state. Derived pages such as `scope.html`,
`context.html`, `learnings.html`, lane pages, and `scope-projection.json/js` are read-only context unless
their owning skill says otherwise.

## The five protocols the agent obeys

The protocols form a stack — each one constrains the layers above it.

### 1. Research Workflow (`workflow.ts` in the toolbox repo)

The executable controller for any package: legal states, run ticket generation, adaptive live monitoring, open-run stop gates, and multi-experiment routing. Call it from a consuming project through the installed toolbox path:

```bash
node <pipeline-root>/workflow.ts next --json '<snapshot>'
node <pipeline-root>/workflow.ts schema
```

Strictly follow the returned ticket: apply its `requiredMutations` through `research-op`, emit each
`perRun[].statusLine`, and do not end a turn unless `stopGate.ok` is true or the ticket records the
smallest blocking user decision.

### 2. Research Output Contract

Research packages live under `research_html/packages/<YYYY-MM-DD>-<slug>/` and are created or materially
restructured through `/research-package`, never by ad-hoc folders. Materialization reads only committed
Scope state, not pending Triage proposals. Runtime logs, metrics, event manifests, checkpoints, and
temporary artifacts go under `outputs/<YYYY-MM-DD>-<slug>/`.

Current package canon: packages use `index.html`, `plan.html`, `tracker.html`, `results.html`,
`docs/index.html`, and `_agent/context.html`, with optional `implementation.html`, `analysis.html`,
conversion-only `brainstorm.html`, and package-local `scripts/`. `tracker.html` owns execution state and
`tracker.html#chosen-route`; standalone `launch.html`, `live.html`, and `next-action.html` are retired.
Typed `experiments[]` rows are the task spine; `learnings_lint.py alignment` verifies their result,
implementation, docs, and tracker thread before launch or lane moves.
For detailed field ownership, load `skills/research-package/references/package-contract.md` only when a
package task needs it.

### 3. Fact Propagation Contract

Every artifact that lands during a research run (checkpoint, candidate JSON, sentinel, phase marker, chain-done) is a "locked fact" that the agent must propagate to every owning surface — `results.html`, `tracker.html#chosen-route`, registry status fields, tracker Resume Block — in the same turn the artifact is observed.

The mechanical check is `/research-op scan-events` (shipped with the `research-op` skill at `skills/research-op/scripts/research_op.py`):

```bash
# every per-turn live cycle
python skills/research-op/scripts/research_op.py --pkg <pkg-id> --op scan-events   # list newly-locked facts as JSON event lines
# … agent invokes --event <name> --payload <json> per event for atomic fan-out …
# The cursor advances on the next successful --event invocation (no separate --bump step).
```

The cursor lives at `<runtime-root>/manifests/.propagation_cursor` (epoch float). An empty report = nothing to propagate. A non-empty report at the Stop Gate is a workflow violation.

**Directive changes are locked facts too (`DIRECTIVE_CHANGE`).** A *user instruction that changes a package's constraints, plan, or scope* — "add a rule", "redesign experiment P1", "change the metric/baseline/roster" — is a locked fact on the same footing as an artifact event. It is not surfaced by `scan-events` (no artifact landed), so the agent must propagate it explicitly in the same turn: write the directive to its typed home (a binding rule → `/research-op insert --target rule` with `level=package, kind=binding`; a plan/scope change → its owning surface), **and** update the tracker Resume Block `lastAction`/`workflow-state` **and** the registry `lastUpdated`. A directive that touches only one surface (e.g. a rule buried in a doc while the tracker and registry read unchanged) is a propagation violation — `learnings_lint.py lint-status` flags it as `directive-not-propagated`.

### 4. Learnings Update Protocol

The cross-package learnings index at `research_html/learnings.html` is a derived view over `research_html/data/research-packages.js`. The data file is the canonical store; `learnings.html` re-renders on page load. This protocol fixes *when* to write to the data file and *how* to keep it trustworthy.

**Core principles**

1. **Upstream surface is the witness, the data file is the index.** A `methodsTried[]` row is written to `research-packages.js` *only after* the corresponding row exists in the package's `results.html` with a stable section anchor, and the `evidencePath` resolves to a real file or anchor. Never invent a row from memory.
2. **Drafts are auto-detected; writes are user-acked at terminal transitions.** In-progress facts (`VERDICT_FINALIZED`, `STATUS_CHANGED`) update without user ack because the source-of-truth surface already exists. Terminal facts (`TERMINAL_TRANSITION`, `ADOPTION`, `SUPERSESSION`, `REOPEN`) require T1 user ack.
3. **Atomic per-turn closure.** Any turn that mutates a learnings-relevant field must, in the same turn, touch all of: upstream surface row → `research-packages.js` → tracker Resume Block `lastAction` → run `learnings_lint.py`. A non-empty lint report is a Stop-Gate violation.

**Event trigger table**

Learnings event names (`LEARNINGS_EVENT` constant — SSOT: this file): `DIRECTIVE_CHANGE`, `VERDICT_FINALIZED`, `STATUS_CHANGED`, `TERMINAL_TRANSITION`, `ADOPTION`, `SUPERSESSION`, `REOPEN`.

| Event | Trigger (where it originates) | User ack | Fields written in `research-packages.js` |
| --- | --- | --- | --- |
| **`DIRECTIVE_CHANGE`** | A user instruction changes the package's constraints / plan / scope (add a binding rule, redesign an experiment, change metric / baseline / roster) — not an artifact event, so `scan-events` will not surface it | none | Write the directive to its typed home (a `data/rules.js` registry row via `--target rule`, or the owning surface) + `lastAction`, `lastUpdated` |
| **`VERDICT_FINALIZED`** | `results.html` result-gate row gains `PASS` / `FAIL` / `INCONCLUSIVE` / `DIAGNOSTIC` AND artifact verification recorded | none | Append one `methodsTried[]` row |
| **`STATUS_CHANGED`** | tracker live-check, plan revision, blocker change | none | `status`, `activeGate`, `primaryMetricVsGate`, `currentBlocker`, `openRuns`, `lastAction`, `lastUpdated` |
| **`TERMINAL_TRANSITION`** | `tracker.html#chosen-route` resolves to a terminal lane move (`TERMINATE`, adoption) | **T1** | `category` (lane move), `status` (terminal value), `terminationMessage`; freeze `methodsTried[]` |
| **`ADOPTION`** | `CLAUDE.md` "Current Best" edit, code merge into `models/` / `trainer/`, or a new in-progress package starts citing the win | **T1** | `adoptionPath` (specific anchor or path) |
| **`SUPERSESSION`** | A newer success package replaces an older one | **T1** | On the *old* package: `status = WIN_SUPERSEDED`, `supersededBy = <new id>` |
| **`REOPEN`** | User explicitly states a fail package should be revisitable under a named condition | **T1** | `status = ARCHIVED_CONDITIONAL`, `reopenTrigger = "<condition>"` |

**`methodsTried` row contract**

Every row is exactly six fields, drawn verbatim from the witnessing `results.html` row:

```
{ method, hypothesis, gate, measured, verdict, evidencePath }
```

- `verdict` ∈ `{PASS, FAIL, INCONCLUSIVE, DIAGNOSTIC}`. Diagnostic-only rows use `DIAGNOSTIC` (not `INCONCLUSIVE`). Single-seed or ambiguous results use `INCONCLUSIVE`.
- `evidencePath` must resolve. Either a file under `outputs/...` / `output/...`, or an HTML anchor like `packages/<id>/results.html#<exp-anchor>`. If the anchor doesn't exist yet, write the row only after creating it.
- N upstream result-gate rows may collapse to 1 `methodsTried` row when they share a method (e.g., a 9-cell sweep summarized as one entry that links to the cell-level data). Prefer aggregation.
- Single-seed `PASS` is `INCONCLUSIVE` until the gate's seed requirement is met. Runs producing only diagnostic evidence (no hypothesis test) use `DIAGNOSTIC`.

**The dashboard-wide tool: `research_html/scripts/learnings_lint.py`**

| Command | What it does |
| --- | --- |
| `lint-status` | Schema lint per package: `(category, status)` legal; required fields present; forbidden fields absent; `methodsTried` rows have the six fields and a legal verdict; cross-references (`supersededBy`, `promotedTo`) resolve; on-disk `packages/<id>/` ⇄ registry entries match. |
| `lint-evidence` | Every `methodsTried[].evidencePath` and `lastDecisionEvidencePath` resolves. File-missing is a warning; anchor-missing is an error. |
| `scan-events [--pkg <id>]` | Runs the three draft writers (`VERDICT_FINALIZED` / `TERMINAL_TRANSITION` / `ADOPTION`). Prints JSON drafts; does not write. |
| `draft-method <pkg-id> <anchor>` | Print one JSON `methodsTried` row drafted from `results.html#<anchor>`. |
| `draft-terminal <pkg-id>` | Print the JSON terminal block drafted from `tracker.html#chosen-route` (legacy packages may fall back to `next-action.html#chosen-route`). |
| `alignment [--pkg <id>] [--terminal]` | Structural task-spine lint: typed `experiments[]` rows have the required result, implementation, docs, and tracker blocks; reverse orphan rows/cards and status contradictions are reported. |
| `all [--pkg <id>]` | All three lints + scan. Exit non-zero if any error was found. |

Add `--strict` to make warnings count toward the exit code (CI mode).

**Stop-Gate sequence (the contract for every learnings-relevant turn)**

1. Make the upstream-witness edit (`results.html` / `tracker.html#chosen-route` / `tracker.html`).
2. Update `research_html/data/research-packages.js`.
3. Update tracker Resume Block `lastAction`.
4. Run `python research_html/scripts/learnings_lint.py all`. Fix every error before closing the turn.
5. If the turn includes a terminal status transition (`TERMINAL_TRANSITION` / `ADOPTION` / `SUPERSESSION` / `REOPEN`), confirm user ack is in hand.

### 5. Refinement Guardrails

Treat the consuming project's contribution spine as a compatibility constraint unless the user explicitly asks to replace it. Every refinement must explain why the design sharpens the current research story, not just why it is novel in isolation.

Each consuming project declares its **non-negotiable contribution spine** as cards in `RESEARCH_PROJECT_PROFILE` in `research_html/data/research-packages.js` (or as a numbered list in the project's own CLAUDE.md). By default, push back on refinements that:

- Remove a spine component without a strong reviewer-proof reason
- Break the Stage-1 → Stage-2 handoff (if the project has one)
- Discard a co-training or progressive-training schedule
- Weaken prior-state code/data consistency

When a refinement direction is explicitly judged failed, remove all worktrees created for that direction after preserving any needed notes in the owning research package.

## The state model that ties protocols 2-4 together

`research_html/data/schema.js` declares the `(category, status)` state machine and the required-field rules each cell must satisfy. The card renderer and `learnings_lint.py` both import from it.

**Naming convention:** Package *category* (lane) values are lowercase-kebab (`in-progress`, `success`, `fail`) — they are URL/CSS/attribute facets. Package *status* values are SCREAMING_SNAKE — they are state-machine positions. Never recase the lane values; never use lowercase for status values.

```
category=in-progress → status ∈ { CONTEXT_LOADED, IMPLEMENTING, IMPLEMENTATION_REVIEW,
                                  DECISION_ADJUDICATION, READY_TO_LAUNCH, EXPERIMENT_RUNNING,
                                  LIVE_ANALYSIS, RESULT_ANALYSIS, NEXT_ACTION_READY,
                                  BLOCKED, STOPPED }
category=success     → status ∈ { ADOPTED_UNCONFIRMED, ADOPTED, WIN_SUPERSEDED }
category=fail        → status ∈ { ARCHIVED, ARCHIVED_CONDITIONAL }
```

`STOPPED` is a terminal-within-lane state: it requires `terminationMessage` and is exempt from the `activeGate`/`primaryMetricVsGate`/`nextRoute` trio. `DECISION_ADJUDICATION` is a transient active state that keeps the full trio.

Brainstorm is **not** a package category. Pre-package, pre-SSOT ideas live on the dashboard brainstorm
lane (`research_html/data/brainstorms.js`); they become a package only at conversion (`/research-brainstorm`
→ a ratified Direction → `create_from_scope`), which freezes the source idea(s) into the package's
`brainstorm.html` provenance sub-page.

Field requirements key off `(category, status)`:

- `category=in-progress` (except `STOPPED`): requires `activeGate`, `primaryMetricVsGate`, `nextRoute`.
- `category=in-progress`, `status=STOPPED`: requires `terminationMessage`; exempt from the trio above.
- `category=success`: requires `terminationMessage`, `methodsTried`, `adoptionPath`.
- `category=fail`: requires `terminationMessage`, `methodsTried`; `reopenTrigger` iff `status=ARCHIVED_CONDITIONAL`.

Terminal transitions (any status change that crosses a lane boundary) require user ack per Trust rule T1.

## Cross-cutting agent rules

- **Build context first.** Read the invocation, project profile, Scope SSOT, package state, active plan,
  results, docs, and runtime evidence required by the task before work.
- **Use the source-routing model.** Load the SSOT or package witness that owns the decision; use derived
  `research_html` pages for in-context learning, not as mutation targets or final proof.
- **Runtime truth wins.** Validate live runs, logs, outputs, summaries, and artifact roots before changing state. Recalled content is unverified (T3).
- **Use live-run artifacts.** For long-running experiment commands, use the project live-run skill when available. Routine live state comes from structured runtime artifacts, not ad hoc raw scrollback parsing; raw logs are bounded debug fallback.
- **Use the resource registry.** When a project resource registry (`outputs/_resources/servers.json`) exists, server connection/capacity facts and experiment placement come from it and its allocation ledger via the resource skill — not from recalled prose; occupancy claims cite ledger entries.
- **Consult Learnings before new directions.** Open `research_html/learnings.html` before proposing a new direction, refinement, or experiment idea, and before converting a brainstorm idea into a package.
- **Surgical changes.** Touch only what the task requires. Match existing style. Do not refactor adjacent code.
- **No A0 reproduction by default.** Trust the recorded checkpoint and `AGENTS.md` / `CLAUDE.md` unless the user explicitly asks to revalidate the anchor.
- **All long-running work goes in `tmux`.** Named sessions/windows so the run can be monitored live; report the attach command.
- **ETA discipline.** Do not pre-estimate run duration. Plan rows, launcher manifests, allocation rows, and live-check rows record `est_time=unknown` until the run has executed at least 30 minutes of stable throughput; after that, derive ETA from observed throughput and update on every 10-minute report.

## Per-project customization

A consuming project's CLAUDE.md should prepend (above this file's content) sections for:

- **Project** — one-paragraph description (system, datasets, agent stack).
- **Motivation and Goal** — the central bottleneck the project attacks.
- **Global Optimization Objective** — the primary objective and the success rule (e.g., "metric X must improve under budget Y").
- **Project-specific rules** — non-negotiable dataset / budget / evaluation constraints.
- **Refinement Guardrails — Contribution Spine** — the project's non-negotiable spine components (mirrored into `RESEARCH_PROJECT_PROFILE.cards`).
- **Current Best** — the live anchor record (checkpoint path, metric values, validation seeds).

These project-specific sections are written by the user. The five protocols above stay verbatim.
