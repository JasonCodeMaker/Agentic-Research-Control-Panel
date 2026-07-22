# AGENTS.md - Trustworthy Research Pipeline for Codex

This file is the Codex-facing operating contract for the Trustworthy Research Pipeline. It translates
the shared protocol in `CLAUDE.md` and the executable package controller in `workflow.ts` into
actions Codex can take inside this toolbox repo or inside a target research project.

Do not treat this file as a weaker copy of `CLAUDE.md`. `CLAUDE.md` remains the durable shared research
contract; this file is the thin Codex bootloader that tells Codex where to start, which skill owns the
task, which source-of-truth layer to load, and when to stop for user ratification.

## First Decision: Where Am I?

Before acting, classify the current working directory:

- **Toolbox repo**: this repository, whose git root is the directory containing this file, `README.md`,
  `CLAUDE.md`, `workflow.ts`, `skills/`, and `lib/`. The parent workspace is not the repo.
- **Target research project**: a consuming ML/research repo where the pipeline has been attached. It may
  contain copied or merged `AGENTS.md`, `CLAUDE.md`, a versioned `.research/` root, and project
  source/config/data files.

If the user asks to change the pipeline implementation or protocol, work in the toolbox repo. If the
user asks to run research, initialize a project, inspect experiments, or update package state, work in
the target research project and resolve pipeline scripts through installed Codex skills.

## Required Read Order

For any non-trivial target-project task, read only the relevant files in this order:

1. User request and any active project-specific section at the top of `AGENTS.md` or `CLAUDE.md`.
2. `CLAUDE.md` for the project-level operating contract and project-specific guardrails.
3. `workflow.ts` contract output before any research-package implementation, launch, monitoring,
   result analysis, or package state transition.
4. The relevant skill body under `$HOME/.codex/skills/<skill-name>/SKILL.md`, or `skills/<skill-name>/`
   when editing this toolbox.
5. The smallest live authority set for the task: `research-op context <package-id>` for governed intent
   and knowledge, plus that experiment's run/result files for measurements.

Runtime artifacts and live process state override remembered summaries. If a required fact is missing,
record the gap and stop at the smallest useful user decision instead of inventing intent.

Source hierarchy: `.research/state/events.jsonl` owns governed intent and management history;
`.research/experiments/<package>/<experiment>/<run>/` owns executed commands, measurements, and evidence;
`.research/audit/actions.jsonl` owns command outcomes. `.research/state/current.json` and the entire
`.research/interface/` tree are rebuildable projections. Agents use `research-op` queries and never read
the interface as an authority.

## Cold Start Skill Routing

Do not load every `research-*` skill body at session start. Codex and Claude discover skill metadata first;
the full `SKILL.md` body is loaded only when the task matches that skill or the user invokes it explicitly.
For ambiguous target-project research workflow requests, use this lifecycle only to avoid skipping
prerequisites:

`onboard(Project Scope) -> brainstorm -> package(convert/refine/finalize Scope) -> run`

If the user names a specific skill, file, surface, script, or operation, go directly to that owner instead
of forcing the lifecycle route.

`research-auto` is the campaign-level entrypoint when its installed skill metadata matches the task; it
still routes through the same Scope, package, run, and mutation boundaries. Use `research-op` for guarded
Scope/package/registry/rule mutations, `research-exp-live` for structured long-running experiment state,
`research-resource` for compute placement/allocation, and `research-analysis` for package Rules/Insights.
The exact trigger boundaries live in the installed skill descriptions; after choosing a skill, read only
that skill body and its directly referenced contract files.

## Setup And Script Resolution

Setup and attach work is occasional, not ordinary cold-start context. Route target-repo setup, attach,
migration, and setup repair through `research-init`; do not overwrite existing target `AGENTS.md` /
`CLAUDE.md` instructions. Setup starts or reuses the Dashboard Server by default and must report its URL,
health, host, port, and stop command. The pipeline is not active for research execution until a Project node
is committed.

In a target research project, do not assume this toolbox source tree is vendored into the repo. Resolve
relative `skills/<name>/scripts/...` commands through the installed Codex skill first
(`$HOME/.agents/skills/<name>/...`). When editing this toolbox repo itself, use the local `skills/<name>/...`
path and run the relevant maintainer checks available in this checkout.

## Scope And Triage Contract

Scope is the versioned intent model for Project -> Direction -> Experiment. A former Task is represented
as `Experiment.spec`; it is not a second executable entity. Codex must preserve this boundary:

- Project objectives, Directions, Experiments, and Scope revisions go through Triage first. A pending idea
  begins as a standalone Brainstorm; only explicit user approval converts it to a non-executable Draft Package.
- Codex may draft proposals and show them to the user, but it must not silently commit
  a Scope event.
- A committed Scope transition requires explicit human ratification and the gated writer documented by
  `research-scope` / `research-op`.
- Interface projection files are read-only. Do not hand-edit them to change intent.

If state and the interface disagree, treat state as the management authority and run artifacts as the
evidence authority. Rebuild the interface after repairing the typed source through its gated operation.

The normal ordering is Project Scope -> standalone Brainstorm and refinement -> explicit conversion approval
-> Draft Package and refinement -> one full Direction-and-Experiments proposal -> one final approval that
atomically commits Scope and activates the same Package. Scope is the commit boundary for mature intent, not
the authoring shell for a vague proposal. The final proposal must bind the exact package id, draft revision,
and document hash.

## Research Package Operation Contract

For package work, Codex is the decision owner governed by `workflow.ts`:

- Load the bounded package context, selected Experiment spec, and relevant run results before acting.
- A Draft Package context contains the canonical proposal document but no selected Experiment and no
  execution authority. Do not send it through workflow launch paths until one user-approved
  `PackageActivated` atomically records `SCOPE_READY`, commits Direction and Experiments, and leaves the
  same aggregate `ACTIVE / CONTEXT_LOADED`.
- Use `/research-op` for every management mutation. Direct edits to state JSON, generated HTML, JavaScript,
  CSV, or package docs are violations.
- Treat user instructions that change constraints, plan, metric, baseline, or scope as locked facts. Record
  them in the typed home and propagate status in the same turn.
- Run the required state, evidence, and projection checks after a management mutation, and fix errors
  before claiming the turn is complete.
- Put long-running experiments, training, preprocessing, downloads, and remote jobs in named `tmux`
  sessions unless the user explicitly asks for a different runner.
- For long-running experiment commands, use the project live-run skill (`research-exp-live`) when
  available: launch through its wrapper and read routine run state from structured runtime artifacts
  (`status.json`), not raw scrollback; raw logs are bounded debug fallback.
- Generate the next package run ticket with:
  `node <pipeline-root>/workflow.ts next --json '<snapshot>'` or `--input <snapshot.json>`.

Do not declare a win from chat memory. Claims need metric gates, evidence paths, and the package/result
surface required by `CLAUDE.md` and the `workflow.ts` ticket.

## Toolbox Maintenance Contract

When modifying this toolbox repo:

- Keep changes surgical and preserve project-agnostic protocol bodies unless the task explicitly asks to
  change them.
- Read `README.md` and the relevant `skills/*/SKILL.md` before changing setup, dashboard, Scope, package,
  or operation behavior; keep detailed runbooks in those owning locations rather than in this always-loaded
  bootloader.
- Behavior changes must be covered by maintainer-side verification before release. In release checkouts
  where developer checks are intentionally absent, run syntax or contract checks appropriate to the
  touched files before claiming toolbox behavior changes are complete.
- Do not modify target-project artifacts while working on toolbox internals unless the user explicitly asks
  for an end-to-end consuming-project test.

## Completion Standard

Before final response, Codex must be able to state:

- which context it operated in: toolbox repo or target research project;
- which protocol or skill controlled the work;
- what files or surfaces changed;
- what validation ran, or why validation was not applicable;
- whether any human ratification is still required.
