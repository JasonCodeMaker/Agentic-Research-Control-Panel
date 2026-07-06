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
  `CLAUDE.md`, `workflow.ts`, `skills/`, `lib/`, and `tests/`. The parent workspace is not the repo.
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

## Attaching The Pipeline To A Target Project

When setting up a target research repo for Codex:

1. Install toolbox skills by symlinking `skills/research-*` into `$HOME/.codex/skills`; do not copy skill
   directories.
2. Copy or merge `AGENTS.md` and `CLAUDE.md` into the target repo root.
3. If the target already has `AGENTS.md` or `CLAUDE.md`, merge the pipeline protocol without overwriting
   existing user/project instructions.
4. Prepend target-specific context above the reusable protocol sections:
   - project objective and motivation;
   - datasets, baselines, metrics, gates, and success criteria;
   - compute constraints and available machines;
   - non-goals, safety constraints, reviewer concerns, and current best checkpoint.
5. Create `outputs/_scope/` and `outputs/_selfevolve/`, then run `/research-dashboard`.
6. If no committed Project node exists, run `/research-onboard` for an existing repo or `/research-scope`
   when the user already knows the exact Project objective.

The pipeline is not active for research execution until a Project node is committed in the Scope SSOT.
Onboarding and scoping may propose; only a human-ratified transition commits the objective.

## Codex Skill And Script Resolution

In a target research project, do not assume this toolbox source tree is vendored into the repo.

- Resolve `skills/<name>/scripts/...` through the installed Codex skill first:
  `$HOME/.codex/skills/<name>/scripts/...`.
- If a command in `CLAUDE.md`, `workflow.ts`, or a skill body uses a relative `skills/...` path, adapt it
  to the installed skill path when running from the target project.
- When editing this toolbox repo itself, use the local `skills/<name>/...` path and run the toolbox tests.

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
  or operation behavior.
- Update tests with behavior changes and run `python3.13 -m pytest tests/` before claiming toolbox
  behavior changes are complete. For documentation-only changes, at minimum run a syntax/consistency check
  appropriate to the touched files.
- Do not modify target-project artifacts while working on toolbox internals unless the user explicitly asks
  for an end-to-end consuming-project test.

## Completion Standard

Before final response, Codex must be able to state:

- which context it operated in: toolbox repo or target research project;
- which protocol or skill controlled the work;
- what files or surfaces changed;
- what validation ran, or why validation was not applicable;
- whether any human ratification is still required.
