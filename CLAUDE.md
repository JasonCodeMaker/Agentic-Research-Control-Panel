# CLAUDE.md — Trustworthy Research Pipeline

This file is the agent operating context for any project that adopts the Trustworthy Research Pipeline. It is intentionally project-agnostic. A consuming project copies this file into its repo root and **prepends** project-specific sections (project name, motivation, optimization objective, contribution spine, current best, dataset / budget gates) above the protocols below. The protocols themselves are universal — do not edit them per project.

## What this pipeline produces

A trustworthy research record where every claim is gated by an explicit metric, every metric is backed by a verified artifact, every direction has one declared next route, and every adopted win or archived failure leaves a structured `methodsTried` trace the next session can learn from. The two skills bundled with this repo — `research-dashboard` and `research-package` — install the HTML surfaces and tooling that enforce this. `WORKFLOW.md` is the seven-step controller the agent follows inside any package.

## The five protocols the agent obeys

The protocols form a stack — each one constrains the layers above it.

### 1. Research Workflow (`WORKFLOW.md` at the repo root)

The seven-step controller for any package: how to load context, when to dispatch a sub-agent, what to emit on the 10-minute live cycle, when to schedule re-entry, when to stop. `WORKFLOW.md` is the operating protocol for any `@WORKFLOW.md` invocation; it overrides general harness defaults (do not spawn agents unless asked, end-of-turn summary style, etc.) inside a research session.

Strictly follow `WORKFLOW.md`: when it says dispatch a sub-agent, dispatch; when it says emit a 10-minute status line, emit it; when it says schedule re-entry, schedule.

### 2. Research Output Contract

The only valid in-repo location for new research material is `research/active/<YYYY-MM-DD>-<slug>/` (a research package).

Every research package must contain:

- `README.md`, `plan.html`, `tracker.html`, `results.html` (plus `index.html`, `next-action.html`, optional `implementation.html` and `brainstorm.html`)
- `docs/` and `_agent/` directories
- A `scripts/` directory for any package-local one-off scripts (optional). Fact propagation is handled centrally by `/research-op scan-events`, not by per-package byte-copies.

Use `bash scripts/dev/new_research.sh <slug>` (or `/research-package`) to create research packages. Do not create ad-hoc top-level research folders outside `research/`.

Runtime state, supervisor JSON, local logs, and temporary CSVs go under `outputs/<YYYY-MM-DD>-<slug>/`, not in tracked repo roots.

When a research theme is complete or paused, move the whole package to `research/archive/<YYYY-MM-DD>-<slug>/`.

Stable shared entrypoints stay in `scripts/`; one-off experiment scripts belong in the owning research package.

### 3. Fact Propagation Contract

Every artifact that lands during a research run (checkpoint, candidate JSON, sentinel, phase marker, chain-done) is a "locked fact" that the agent must propagate to every owning surface — `results.html`, `next-action.html`, registry status fields, tracker Resume Block — in the same turn the artifact is observed.

The mechanical check is `/research-op scan-events` (shipped with the `research-op` skill at `skills/research-op/scripts/research_op.py`):

```bash
# every per-turn live cycle
python skills/research-op/scripts/research_op.py --pkg <pkg-id> --op scan-events   # list newly-locked facts as JSON event lines
# … agent invokes --event <name> --payload <json> per event for atomic fan-out …
# The cursor advances on the next successful --event invocation (no separate --bump step).
```

The cursor lives at `<runtime-root>/manifests/.propagation_cursor` (epoch float). An empty report = nothing to propagate. A non-empty report at the Stop Gate is a workflow violation.

**Directive changes are locked facts too (E0).** A *user instruction that changes a package's constraints, plan, or scope* — "add a rule", "redesign experiment P1", "change the metric/baseline/roster" — is a locked fact on the same footing as an artifact event. It is not surfaced by `scan-events` (no artifact landed), so the agent must propagate it explicitly in the same turn: write the directive to its typed home (a binding rule → `/research-op insert --target package-invariant`; a plan/scope change → its owning surface), **and** update the tracker Resume Block `lastAction`/`workflow-state` **and** the registry `lastUpdated`. A directive that touches only one surface (e.g. a rule buried in a doc while the tracker and registry read unchanged) is a propagation violation — `learnings_lint.py lint-status` flags it as `directive-not-propagated`.

### 4. Learnings Update Protocol

The cross-package learnings index at `research_html/learnings.html` is a derived view over `research_html/data/research-packages.js`. The data file is the canonical store; `learnings.html` re-renders on page load. This protocol fixes *when* to write to the data file and *how* to keep it trustworthy.

**Core principles**

1. **Upstream surface is the witness, the data file is the index.** A `methodsTried[]` row is written to `research-packages.js` *only after* the corresponding row exists in the package's `results.html` with a stable section anchor, and the `evidencePath` resolves to a real file or anchor. Never invent a row from memory.
2. **Drafts are auto-detected; writes are user-acked at terminal transitions.** In-progress facts (E1, E2 below) update without user ack because the source-of-truth surface already exists. Terminal facts (E3–E6) require T1 user ack.
3. **Atomic per-turn closure.** Any turn that mutates a learnings-relevant field must, in the same turn, touch all of: upstream surface row → `research-packages.js` → tracker Resume Block `lastAction` → run `learnings_lint.py`. A non-empty lint report is a Stop-Gate violation.

**Event trigger table**

| Event | Trigger (where it originates) | User ack | Fields written in `research-packages.js` |
| --- | --- | --- | --- |
| **E0. Directive change** | A user instruction changes the package's constraints / plan / scope (add a binding rule, redesign an experiment, change metric / baseline / roster) — not an artifact event, so `scan-events` will not surface it | none | Write the directive to its typed home (`bindingRules[]` via `--target package-invariant`, or the owning surface) + `lastAction`, `lastUpdated` |
| **E1. Per-experiment verdict finalized** | `results.html` result-gate row gains `pass` / `fail` / `inconclusive` AND artifact verification recorded | none | Append one `methodsTried[]` row |
| **E2. In-progress live update** | tracker live-check, plan revision, blocker change | none | `status`, `activeGate`, `primaryMetricVsGate`, `currentBlocker`, `openRuns`, `lastAction`, `lastUpdated` |
| **E3. Terminal status transition** | `next-action.html` chosen-route resolves to a terminal lane move (`archive_or_stop`, adoption) | **T1** | `category` (lane move), `status` (terminal value), `terminationMessage`; freeze `methodsTried[]` |
| **E4. Adoption** | `CLAUDE.md` "Current Best" edit, code merge into `models/` / `trainer/`, or a new in-progress package starts citing the win | **T1** | `adoptionPath` (specific anchor or path) |
| **E5. Supersession** | A newer success package replaces an older one | **T1** | On the *old* package: `status = SUPERSEDED`, `supersededBy = <new id>` |
| **E6. Reopen marked** | User explicitly states a fail package should be revisitable under a named condition | **T1** | `status = ARCHIVED_REOPENABLE`, `reopenTrigger = "<condition>"` |

**`methodsTried` row contract**

Every row is exactly six fields, drawn verbatim from the witnessing `results.html` row:

```
{ method, hypothesis, gate, measured, verdict, evidencePath }
```

- `verdict` ∈ `{pass, fail, inconclusive}`. Diagnostic-only rows are `inconclusive`, not `pass`.
- `evidencePath` must resolve. Either a file under `outputs/...` / `output/...`, or an HTML anchor like `packages/<id>/results.html#<exp-anchor>`. If the anchor doesn't exist yet, write the row only after creating it.
- N upstream result-gate rows may collapse to 1 `methodsTried` row when they share a method (e.g., a 9-cell sweep summarized as one entry that links to the cell-level data). Prefer aggregation.
- Single-seed `pass` is `inconclusive` until the gate's seed requirement is met.

**The dashboard-wide tool: `research_html/scripts/learnings_lint.py`**

| Command | What it does |
| --- | --- |
| `lint-status` | Schema lint per package: `(category, status)` legal; required fields present; forbidden fields absent; `methodsTried` rows have the six fields and a legal verdict; cross-references (`supersededBy`, `promotedTo`) resolve; on-disk `packages/<id>/` ⇄ registry entries match. |
| `lint-evidence` | Every `methodsTried[].evidencePath` and `lastDecisionEvidencePath` resolves. File-missing is a warning; anchor-missing is an error. |
| `scan-events [--pkg <id>]` | Runs the three draft writers (E1 / E3 / E4). Prints JSON drafts; does not write. |
| `draft-method <pkg-id> <anchor>` | Print one JSON `methodsTried` row drafted from `results.html#<anchor>`. |
| `draft-terminal <pkg-id>` | Print the JSON terminal block drafted from `next-action.html#chosen-route`. |
| `all [--pkg <id>]` | All three lints + scan. Exit non-zero if any error was found. |

Add `--strict` to make warnings count toward the exit code (CI mode).

**Stop-Gate sequence (the contract for every learnings-relevant turn)**

1. Make the upstream-witness edit (results.html / next-action.html / tracker.html).
2. Update `research_html/data/research-packages.js`.
3. Update tracker Resume Block `lastAction`.
4. Run `python research_html/scripts/learnings_lint.py all`. Fix every error before closing the turn.
5. If the turn includes a terminal status transition (E3–E6), confirm user ack is in hand.

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

```
category=in-progress → status ∈ { CONTEXT_LOADED, IMPLEMENTING, IMPLEMENTATION_REVIEW,
                                  READY_TO_LAUNCH, EXPERIMENT_RUNNING, LIVE_ANALYSIS,
                                  RESULT_ANALYSIS, NEXT_ACTION_READY, BLOCKED }
category=success     → status ∈ { ADOPTED_PENDING_ACK, ADOPTED, SUPERSEDED }
category=fail        → status ∈ { ARCHIVED, ARCHIVED_REOPENABLE }
```

Brainstorm is **not** a package category. Pre-package, pre-SSOT ideas live on the dashboard brainstorm
lane (`research_html/data/brainstorms.js`); they become a package only at conversion (`/research-brainstorm`
→ a ratified Direction → `create_from_scope`), which freezes the source idea(s) into the package's
`brainstorm.html` provenance sub-page.

Field requirements key off `(category, status)`:

- `category=in-progress`: requires `activeGate`, `primaryMetricVsGate`, `nextRoute`.
- `category=success`: requires `terminationMessage`, `methodsTried`, `adoptionPath`.
- `category=fail`: requires `terminationMessage`, `methodsTried`; `reopenable` iff `status=ARCHIVED_REOPENABLE`.

Terminal transitions (any status change that crosses a lane boundary) require user ack per Trust rule T1.

## Cross-cutting agent rules

- **Build context first.** Read the invocation, project profile, package state, active plan, results, and docs before work.
- **Runtime truth wins.** Validate live runs, logs, outputs, summaries, and artifact roots before changing state. Recalled content is unverified (T3).
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
