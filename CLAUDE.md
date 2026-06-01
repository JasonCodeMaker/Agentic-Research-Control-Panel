# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **design / engineering project** whose deliverable is a **Trustworthy Auto-Research Pipeline** — an
autonomous research agent system that extends the existing `Trustworthy-Research-Pipeline/` base and must
solve the three failures named in [核心问题.md](核心问题.md). It is *not* itself a model-training
codebase; the "code" here is skills, protocols (`CLAUDE.md` / `WORKFLOW.md`), HTML surfaces, and the
validators that gate them.

The mandate is in [核心问题.md](核心问题.md) — every design decision must trace back to one of its three
problems and the solution directions it commits to:

1. **Context pollution + hallucination → deception & instruction non-compliance.** Counter with
   structured (typed) interfaces, multi-agent context isolation, *mandatory* Test-Driven implementation,
   and minimizing workflow/pipeline complexity.
2. **No HCI alignment of model ↔ user context.** Counter with a live, real-time-updated HTML dashboard.
3. **No personalized project self-learning.** Counter with a rule-based self-learning framework + a
   self-reflection loop + a durable memory mechanism.

## Layout

| Path | Role |
| --- | --- |
| [核心问题.md](核心问题.md) | The spec: the 3 core problems + committed solution directions. Source of truth for *why*. |
| `Trustworthy-Research-Pipeline/` | The **base pipeline** being extended (its own `CLAUDE.md` / `WORKFLOW.md` / `README.md` + the 4 skills + tests). Read these before changing anything. |
| `.source/` | **Read-only references & brainstorm insight** (git-ignored). `existing_work/` holds ARIS (`Auto-claude-code-research-in-sleep`) and `academic-research-skills` — study, don't import wholesale. |
| `plan/` | Implementation plans live here (currently empty). New design/plan docs go here, not at repo root. |
| `demo/` | Git-ignored rendered demo of the `research_html/` dashboard — reference render, not authoritative. |

`.source/`, `demo/`, and `var/` are git-ignored; treat `.source/` as inputs, never as material to commit.

## The base pipeline (read multiple files to grasp this)

`Trustworthy-Research-Pipeline/` ships **four composing skills** + two protocol files. The big picture only
emerges from reading them together:

- **Skill layering** (`README.md`): `research-dashboard` (once/project — scaffolds `research_html/`,
  `schema.js`, `learnings.html`) → `research-package` (once/pkg — scaffolds the fixed page set) →
  `research-analysis` (mid-freq — Rules + Insights) → `research-op` (per-turn — the **single mutation
  surface**: every Insert/Update/Delete/Check/scan-events/event op).
- **The Mutation Rule** (`WORKFLOW.md`): after scaffolding, *every* edit to a package surface routes
  through `research-op`; direct `Edit`/`Write` on package files is a workflow violation. `research-op`
  enforces a `(category, status, op, target)` legality matrix + per-target invariants (Pattern B:
  reject-before-write) and appends one JSONL audit line per op to `var/research/<pkg>/_actions.jsonl`.
- **State model** (`CLAUDE.md` + `skills/research-dashboard/.../schema.js`): the
  `(category, status)` state machine — `brainstorm` / `in-progress` / `success` / `fail` lanes — drives
  required-field rules, the learnings lint, and terminal-transition user-ack (rule T1).
- **WORKFLOW.md**: the 7-step decision-owner controller (context → implement → review → launch → live →
  analyze → next-action) the agent obeys *inside* a research package. Fact Propagation Contract = every
  landed artifact is propagated to all owning surfaces in the same turn via `research-op scan-events`.

When designing the *auto* layer, preserve these contracts unless [核心问题.md](核心问题.md) demands
changing one — they are the existing trust guarantees, and weakening them must be justified against G1/G2/G3.

## Working rules

- Design before code. For new features/behavior, brainstorm the design against [核心问题.md](核心问题.md)
  first; the spec's own mandate is "minimize workflow/pipeline complexity" and "all implementation must be
  Test-Driven" — honor both.
- Keep solution work traceable to a numbered core problem; don't add capability that no problem in
  [核心问题.md](核心问题.md) asks for.
- Don't edit the base pipeline's universal protocol bodies (the 5 protocols in its `CLAUDE.md`, the steps
  in its `WORKFLOW.md`) casually — they are designed to be project-agnostic. Prepend, don't rewrite.

# Superpowers Lite Mode

Superpowers is installed, but use it selectively.

Default mode is lightweight. Do not automatically run the full Superpowers workflow for small or localized tasks.

## Task classification

### Trivial tasks
Examples: typo fixes, import fixes, one-line changes, simple explanations, small command help.

Rules:
- Do not invoke Superpowers skills.
- Answer or edit directly.
- Run only the most relevant quick check if code changed.

### Standard tasks
Examples: localized bug fix, small feature, refactor touching <= 5 files.

Rules:
- Use a mini-plan instead of full Superpowers workflow.
- Mini-plan must be <= 5 bullets.
- State assumptions briefly.
- Do not write a design doc.
- Do not create files under docs/superpowers/.
- Do not commit unless explicitly asked.
- Do not spawn subagents unless explicitly asked.
- Use tests only when existing tests are relevant or the change is risky.
- After editing, summarize changed files and verification.

### Complex tasks
Examples: architecture changes, migrations, auth/security, data loss risk, production deployment, multi-module refactor, unclear requirements.

Rules:
- Use the full Superpowers workflow.
- Brainstorm first.
- Write a plan.
- Ask for approval before large edits.
- Use TDD and review where appropriate.

## Overrides

- User direct instruction always wins.
- If I say "quick", "simple", "minimal", or "no full workflow", use lightweight mode.
- If I say "full superpowers", use the normal Superpowers workflow.
- Ask at most one clarifying question. If not blocking, make a reasonable assumption and continue.
- Prefer inline execution over subagent-driven execution unless I explicitly request subagents.