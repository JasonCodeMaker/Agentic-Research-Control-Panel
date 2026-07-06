# CLAUDE.md — Trustworthy Research Pipeline

This file is the agent operating context for any project that adopts the Trustworthy Research Pipeline.
It is intentionally project-agnostic. A consuming project copies this file into its repo root and
**prepends** project-specific sections (project name, motivation, optimization objective, contribution
spine, current best, dataset / budget gates) above the protocols below. The protocols themselves are
universal — do not edit them per project.

## What this pipeline produces

A trustworthy research record where every claim is gated by an explicit metric, every metric is backed by
a verified artifact, every direction has one declared next route, and every adopted win or archived failure
leaves a structured `methodsTried` trace the next session can learn from. The skills bundled with this repo
install the HTML surfaces, Scope/Triage gates, orchestration, and mutation tooling that enforce this.
`workflow.ts` is the executable package controller the agent follows inside any package.

`research_html/` is the shared context surface, not the authority by itself. For research-affecting tasks,
load the narrow owning layer: `outputs/_scope/transitions.jsonl` for intent, package pages for
plan/tracker/result witnesses, `outputs/<pkg>/` plus live process state for measurements, and
`research_html/data/research-packages.js` for dashboard index state. Derived pages such as `scope.html`,
`context.html`, `learnings.html`, lane pages, and `scope-projection.json/js` are read-only context unless
their owning skill says otherwise.

## The five protocols the agent obeys

The protocols form a stack. Keep this file as the always-loaded protocol index; load the owning skill,
script help, or reference only when the current task reaches that surface.

### 1. Research Workflow (`workflow.ts` in the toolbox repo)

`workflow.ts` is the executable controller for package work: legal states, run tickets, open-run stop gates,
adaptive live monitoring, and multi-experiment routing. Call it from a consuming project through the
installed toolbox path:

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

Package page canon, field ownership, and large structural rules live in
`skills/research-package/references/package-contract.md`. Load that reference only for package creation,
material restructuring, or ownership disputes.

### 3. Fact Propagation Contract

Every artifact that lands during a research run is a locked fact. Checkpoints, candidate JSONs, sentinels,
phase markers, chain-done markers, and comparable runtime artifacts must be propagated to every owning
surface in the same turn they are observed: results, tracker chosen route, registry fields, and tracker
Resume Block.

Directive changes are locked facts too. A user instruction that changes constraints, plan, metric, baseline,
roster, or scope must be written to its typed home and propagated to tracker/registry state in the same
turn. Use the `research-op` skill for `scan-events`, explicit event fan-out, rule inserts, status repair,
and the exact command/cursor details.

### 4. Learnings Update Protocol

The cross-package learnings index at `research_html/learnings.html` is a derived view over
`research_html/data/research-packages.js`. The data file is the canonical store; `learnings.html`
re-renders on page load. This protocol fixes *when* to write to the data file and *how* to keep it
trustworthy.

Core principles:

- Upstream surfaces are witnesses; `research-packages.js` is the index. Write `methodsTried[]` only from
  verified `results.html` rows with resolving evidence paths.
- In-progress facts can update after their source surface exists. Terminal lane moves, adoption,
  supersession, and reopen decisions require T1 user ack.
- Any learnings-relevant turn must close atomically: witness surface, registry, tracker Resume Block, and
  `learnings_lint.py all` must agree before the turn ends.

Event names, `methodsTried` field details, lint subcommands, and draft writers belong to the dashboard
scripts and `research-op` / `research-analysis` references. Load those only when the turn mutates or audits
learnings-relevant state.

### 5. Refinement Guardrails

Treat the consuming project's contribution spine as a compatibility constraint unless the user explicitly
asks to replace it. Every refinement must explain why the design sharpens the current research story, not
just why it is novel in isolation. Project-specific examples and cleanup rules belong in the prepended
project profile or the owning refinement/package skill.

## The state model that ties protocols 2-4 together

`research_html/data/schema.js` declares the `(category, status)` state machine and required-field rules.
The card renderer and `learnings_lint.py` import from it, so it is the machine-readable authority.

**Naming convention:** Package *category* (lane) values are lowercase-kebab (`in-progress`, `success`,
`fail`) — they are URL/CSS/attribute facets. Package *status* values are SCREAMING_SNAKE — they are
state-machine positions. Never recase the lane values; never use lowercase for status values.

Brainstorm is **not** a package category. Pre-package, pre-SSOT ideas live on the dashboard brainstorm
lane (`research_html/data/brainstorms.js`); they become a package only at conversion (`/research-brainstorm`
→ a ratified Direction → `create_from_scope`), which freezes the source idea(s) into the package's
`brainstorm.html` provenance sub-page.

Terminal transitions (any status change that crosses a lane boundary) require user ack per Trust rule T1.

## Cross-cutting agent rules

- **Build context first.** Read the invocation, project profile, Scope SSOT, package state, active plan,
  results, docs, and runtime evidence required by the task before work.
- **Use the source-routing model.** Load the SSOT or package witness that owns the decision; use derived
  `research_html` pages for in-context learning, not as mutation targets or final proof.
- **Runtime truth wins.** Validate live runs, logs, outputs, summaries, and artifact roots before changing
  state. Recalled content is unverified (T3).
- **Use live-run artifacts.** For long-running experiment commands, use the project live-run skill when
  available. Routine live state comes from structured runtime artifacts, not ad hoc raw scrollback parsing;
  raw logs are bounded debug fallback.
- **Use the resource registry.** When a project resource registry (`outputs/_resources/servers.json`) exists,
  server connection/capacity facts and experiment placement come from it and its allocation ledger via the
  resource skill — not from recalled prose; occupancy claims cite ledger entries.
- **Consult Learnings before new directions.** Open `research_html/learnings.html` before proposing a new
  direction, refinement, or experiment idea, and before converting a brainstorm idea into a package.
- **Surgical changes.** Touch only what the task requires. Match existing style. Do not refactor adjacent code.
- **No A0 reproduction by default.** Trust the recorded checkpoint and `AGENTS.md` / `CLAUDE.md` unless
  the user explicitly asks to revalidate the anchor.
- **All long-running work goes in `tmux`.** Named sessions/windows so the run can be monitored live; report
  the attach command.
- **ETA discipline.** Do not pre-estimate run duration. Plan rows, launcher manifests, allocation rows, and
  live-check rows record `est_time=unknown` until the run has executed at least 30 minutes of stable
  throughput; after that, derive ETA from observed throughput and update on every 10-minute report.

## Per-project customization

A consuming project's CLAUDE.md should prepend (above this file's content) sections for:

- **Project** — one-paragraph description (system, datasets, agent stack).
- **Motivation and Goal** — the central bottleneck the project attacks.
- **Global Optimization Objective** — the primary objective and the success rule (e.g., "metric X must
  improve under budget Y").
- **Project-specific rules** — non-negotiable dataset / budget / evaluation constraints.
- **Refinement Guardrails — Contribution Spine** — the project's non-negotiable spine components (mirrored
  into `RESEARCH_PROJECT_PROFILE.cards`).
- **Current Best** — the live anchor record (checkpoint path, metric values, validation seeds).

These project-specific sections are written by the user. The five protocols above stay verbatim.
