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
  contain copied or merged `AGENTS.md`, `CLAUDE.md`, `research_html/`, `outputs/_scope/`, and project
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
5. The smallest live authority set for the task: Scope for intent, package pages for plans/verdicts,
   runtime artifacts for measurements, and `research_html/data/research-packages.js` for dashboard index
   state.

Runtime artifacts and live process state override remembered summaries. If a required fact is missing,
record the gap and stop at the smallest useful user decision instead of inventing intent.

Source hierarchy: Scope owns intent; package `plan.html` owns executable gates; runtime artifacts own
measurements; package `results.html` owns verdicts; `research-packages.js` owns dashboard index state;
`research_html/data/rules.js` owns the binding-rule corpus (mutated only via `research-op --target rule`;
its `origin=mirror|selfevolve` rows are export-owned projections).
Derived pages (`scope.html`, `learnings.html`, lane pages, `scope-projection.json/js`) are
read surfaces unless their owning skill says otherwise. For detailed surface ownership, read only the
relevant skill/reference, especially `research-dashboard`, `research-package`, `research-op`, and
`research-scope`.

## Cold Start Skill Routing

Do not load every `research-*` skill body at session start. Codex and Claude discover skill metadata first;
the full `SKILL.md` body is loaded only when the task matches that skill or the user invokes it explicitly.
For ambiguous target-project research workflow requests, use this lifecycle only to avoid skipping
prerequisites:

`dashboard -> onboard/scope -> brainstorm -> package -> run`

If the user names a specific skill, file, surface, script, or operation, go directly to that owner instead
of forcing the lifecycle route.

`research-auto` is the campaign-level entrypoint when its installed skill metadata matches the task; it
still routes through the same Scope, package, run, and mutation boundaries. Use `research-op` for guarded
Scope/package/registry/rule mutations, `research-exp-live` for structured long-running experiment state,
`research-resource` for compute placement/allocation, and `research-analysis` for package Rules/Insights.
The exact trigger boundaries live in the installed skill descriptions; after choosing a skill, read only
that skill body and its directly referenced contract files.

## Setup And Script Resolution

Setup and attach work is occasional, not ordinary cold-start context. For target-repo setup, use `README.md`
and the owning setup skills (`research-dashboard`, then `research-onboard` or `research-scope`) without
overwriting existing target `AGENTS.md` / `CLAUDE.md` instructions. The pipeline is not active for research
execution until a Project node is committed in the Scope SSOT.

In a target research project, do not assume this toolbox source tree is vendored into the repo. Resolve
relative `skills/<name>/scripts/...` commands through the installed Codex skill first
(`$HOME/.codex/skills/<name>/...`). When editing this toolbox repo itself, use the local `skills/<name>/...`
path and run the relevant maintainer checks available in this checkout.

## Scope And Triage Contract

Scope is the versioned intent store for Project -> Direction -> Task. Codex must preserve this boundary:

- Pending ideas, Project objectives, Directions, Tasks, and scope revisions go through Triage first.
- Codex may draft proposals and show them to the user, but it must not silently commit
  `outputs/_scope/transitions.jsonl`.
- A committed Scope transition requires explicit human ratification and the gated writer documented by
  `research-scope` / `research-op`.
- Dashboard Scope projection files are read-only derived views. Do not hand-edit them to change intent.

If Scope and package/dashboard surfaces disagree, treat Scope as the intent authority and package/runtime
artifacts as evidence authority; repair through the appropriate gated operation rather than ad-hoc edits.

## Research Package Operation Contract

For package work, Codex is the decision owner governed by `workflow.ts`:

- Read the package Resume Block, active plan, project rules, results, and relevant runtime artifacts before
  acting.
- Use `/research-op` for research-package surface mutations. Direct edits to package HTML, inventory rows,
  or package docs are violations unless the relevant skill explicitly owns scaffolding or large structural
  setup.
- Treat user instructions that change constraints, plan, metric, baseline, or scope as locked facts. Record
  them in the typed home and propagate status in the same turn.
- Run the required lint/check command after learnings-relevant or package-state mutations, and fix errors
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
