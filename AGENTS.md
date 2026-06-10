# AGENTS.md - Trustworthy Research Pipeline for Codex

This file is the Codex adapter for the Trustworthy Research Pipeline toolbox. The durable operating
contract remains in `CLAUDE.md` and `WORKFLOW.md`; do not duplicate or weaken those protocols here.

## Repo Boundary

- The git repo root is this directory, not the parent workspace.
- This repo is the toolbox, not a managed research project. Its `skills/research-*` commands run inside
  target ML repos after installation.

## Required Read Order

1. For setup or framework work, read `README.md` and the relevant `skills/*/SKILL.md` before editing.
2. For agent operating rules, read `CLAUDE.md`.
3. For research-package execution or resume work, read `WORKFLOW.md` and then follow its package-level
   read order.

## Codex Setup Contract

- Install skills for Codex by symlinking `skills/research-*` into `$HOME/.codex/skills`; do not copy.
- When a protocol or skill body shows a script path like `skills/<name>/scripts/...` from inside a
  managed research repo, resolve it through the installed symlink first, e.g.
  `$HOME/.codex/skills/<name>/scripts/...`. Do not assume the target repo contains this toolbox.
- When attaching this pipeline to a target repo for Codex, copy or merge `AGENTS.md`, `CLAUDE.md`, and
  `WORKFLOW.md` at the target repo root.
- If the target already has `AGENTS.md` or `CLAUDE.md`, merge the pipeline protocol instead of
  overwriting user/project instructions.
- Prepend target-specific context above the reusable framework protocol sections.

## Mutation And Testing

- Do not mutate research-package surfaces directly; use `research-op` unless a scaffold exception in
  `WORKFLOW.md` applies.
- Keep changes surgical and preserve project-agnostic protocol bodies unless the task explicitly asks to
  change them.
- Run `python3.13 -m pytest tests/` before claiming toolbox behavior changes are complete.
