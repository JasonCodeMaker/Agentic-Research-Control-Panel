# Trustworthy Research Pipeline

A research workflow scaffold for Claude Code / Codex. It ships **four skills** that build a per-project HTML dashboard, scaffold per-direction research packages, maintain the per-package analysis page (Rules + Insight), and route every package mutation through a single state-gated chokepoint. Plus a `WORKFLOW.md` that the agent follows when implementing each package, and a `CLAUDE.md` that distills the protocols the agent obeys across every project.

## What's in this repo

| File / dir | What it is |
| --- | --- |
| `skills/research-dashboard/` | Skill that scaffolds the project-level `research_html/` dashboard (lanes, schema, learnings page, lint tool). |
| `skills/research-package/` | Skill that scaffolds one research package under `research_html/packages/<YYYY-MM-DD-slug>/` with overview / plan / implementation / results / analysis / next-action / tracker / brainstorm pages. |
| `skills/research-analysis/` | Skill that initializes and validates the per-package `analysis.html` page (Rules + Insight). Manual-only content discipline; visualization templates for inline-styled HTML/CSS bar charts, heatmaps, and admission matrices. Delegates file writes to `research-op`. |
| `skills/research-op/` | **NEW.** The single mutation surface for any existing research package. Routes every Insert / Update / Delete / Check op through a `(category, status, op, target)` state-gate + per-target invariant validators (Pattern B reject-before-write). Composite-event fan-out (`chain-done`, `checkpoint-saved`, `sentinel-write`, `phase-marker`, `candidate-json`) replaces the old `propagate_facts.py` script. Every op invocation (success or reject) appends one JSONL line to `var/research/<pkg>/_actions.jsonl`. Never invokes git. |
| `WORKFLOW.md` | Seven-step controller the agent follows inside any package. Now includes the binding **Mutation Rule** — every package-surface mutation must go through `/research-op`. |
| `CLAUDE.md` | Project-agnostic agent operating context: the protocols (Workflow, Output Contract, Fact Propagation via `/research-op`, Learnings Update, Refinement Guardrails) and the `(category, status)` state model. Consuming projects prepend their own specifics. |

## Skill layering

The four skills compose into four layers, each with its own frequency and scope:

```
LAYER             SKILL                    FREQUENCY     SCOPE
─────────────────────────────────────────────────────────────────────────
Project-init  →   research-dashboard       once/project  Scaffold research_html/, schema.js, learnings.html
Package-init  →   research-package         once/pkg      Scaffold the fixed file set + first inventory entry
Editorial     →   research-analysis        mid-freq      Rules + Insights on analysis.html (delegates writes to research-op)
Mutation      →   research-op              per-turn      All other ops: Insert / Update / Delete / Check / scan-events / event
```

After scaffolding, **every** edit to a package surface — HTML row, inventory field, doc card, status transition — flows through `/research-op`. Direct `Edit` / `Write` on package files is a workflow violation; the Pattern B validators refuse out-of-contract writes before any byte hits disk.

## Installation

### 1. Install the skills

Copy (or symlink) the four skills into your agent's skills directory.

**Claude Code:**

```bash
cp -r skills/research-dashboard ~/.claude/skills/
cp -r skills/research-package   ~/.claude/skills/
cp -r skills/research-analysis  ~/.claude/skills/
cp -r skills/research-op        ~/.claude/skills/
```

**Codex:**

```bash
cp -r skills/research-dashboard ~/.codex/skills/
cp -r skills/research-package   ~/.codex/skills/
cp -r skills/research-analysis  ~/.codex/skills/
cp -r skills/research-op        ~/.codex/skills/
```

Restart the agent so the new skills are picked up.

### 2. Install the agent operating context

Copy `CLAUDE.md` to your research project's repo root, then prepend project-specific sections (project name, motivation, optimization objective, contribution spine, current best) above the protocols. The protocols themselves are universal — do not edit them per project.

```bash
cp CLAUDE.md /path/to/your-research-project/CLAUDE.md
```

Also copy `WORKFLOW.md` if the consuming project doesn't already have its own.

### 3. Initialize the dashboard in your research project

From the root of the research project you want to manage:

```
/research-dashboard
```

This creates the `research_html/` scaffold:

- `index.html` + 4 lane pages (brainstorm / in-progress / success / fail)
- `learnings.html` — cross-package derived view, grouped by contribution spine
- `data/schema.js` — the `(category, status)` state machine and required-field rules
- `data/research-packages.js` — project-agnostic protocol cards and an empty package list
- `scripts/learnings_lint.py` + `scripts/dump_packages.js` — dashboard-wide consistency tool
- `rules/html-rules.html` + `rules/trustworthy-research-rules.html` — the binding rule files

### 4. Create a research package for a specific direction

```
/research-package
```

Or invoke the script directly with the new CLI flags:

```bash
python ~/.claude/skills/research-package/scripts/create_research_package.py \
  --root research_html \
  --id 2026-05-12-my-direction \
  --name "My Direction" \
  --category brainstorm \
  --tag "..." --tag-meaning "..." --problem "..." --objective "..." --motivation "..." \
  --next-action "..." \
  --status EXPLORING \
  --contribution-spine-flag <id-from-schema.js> \
  --direction "one-sentence direction" \
  --scope index,docs,_agent
```

### 5. Implement the package using `WORKFLOW.md` + `/research-op`

Point the agent at [WORKFLOW.md](WORKFLOW.md) when working inside a package. It defines the decision-owner protocol, subagent dispatch rules, the read / authority order the agent must follow, and the **Mutation Rule** that routes every per-turn package edit through `/research-op`.

The `/research-op` invocation interface (used by both the agent and ad-hoc user calls):

```bash
# Primitive ops — agent autonomous + scriptable
python ~/.claude/skills/research-op/scripts/research_op.py --pkg <id> --op insert --target methodsTried --payload '{...}'
python ~/.claude/skills/research-op/scripts/research_op.py --pkg <id> --op update --target status   --payload '{"to":"BLOCKED"}'
python ~/.claude/skills/research-op/scripts/research_op.py --pkg <id> --op delete --target doc-file --payload '{"slug":"obsolete-doc"}'
python ~/.claude/skills/research-op/scripts/research_op.py --pkg <id> --op check  --scope all

# Artifact-event detection + atomic fan-out (replaces propagate_facts.py)
python ~/.claude/skills/research-op/scripts/research_op.py --pkg <id> --op scan-events
python ~/.claude/skills/research-op/scripts/research_op.py --pkg <id> --event chain-done --payload '{"artifact":"..."}'
```

Every invocation — success or reject — appends one JSONL line to `var/research/<pkg>/_actions.jsonl`. To watch the agent live:

```bash
tail -f var/research/<pkg>/_actions.jsonl
```

To find recent rejections (the "agent got stuck" signal):

```bash
grep '"validation": "rejected"' var/research/<pkg>/_actions.jsonl | tail -20
```

## State model and learnings tooling

Every package carries a `status` field whose legal values depend on its lane:

| category | legal `status` values |
| --- | --- |
| brainstorm | `EXPLORING`, `PILOT_READY`, `PROMOTED`, `ABANDONED` |
| in-progress | `CONTEXT_LOADED`, `IMPLEMENTING`, `IMPLEMENTATION_REVIEW`, `READY_TO_LAUNCH`, `EXPERIMENT_RUNNING`, `LIVE_ANALYSIS`, `RESULT_ANALYSIS`, `NEXT_ACTION_READY`, `BLOCKED` |
| success | `ADOPTED_PENDING_ACK`, `ADOPTED`, `SUPERSEDED` |
| fail | `ARCHIVED`, `ARCHIVED_REOPENABLE` |

Required field sets per `(category, status)` and the structured `methodsTried` row shape are declared in `research_html/data/schema.js`. The 33-row `(category, status, op, target)` legality matrix that `/research-op` enforces is declared in `~/.claude/skills/research-op/references/matrix.md` and encoded as Python data in `~/.claude/skills/research-op/scripts/transitions.py`.

The Stop Gate of every learnings-relevant turn requires:

```bash
python research_html/scripts/learnings_lint.py all
python ~/.claude/skills/research-op/scripts/research_op.py --pkg <id> --op scan-events    # should print zero events
```

to exit clean. See the **Learnings Update Protocol** section of [CLAUDE.md](CLAUDE.md) for the full event-trigger × lint-gate × atomic-turn contract.

## Design documents

The architecture and decision audit trail for the `/research-op` skill is captured in:

- [`docs/superpowers/specs/2026-05-24-research-op-skill-control-design.md`](docs/superpowers/specs/2026-05-24-research-op-skill-control-design.md) — the design spec (problem framing, peer-framework survey, ops × states × file matrix, validate rules, audit log, trigger model)
- [`docs/superpowers/plans/2026-05-24-research-op-skill.md`](docs/superpowers/plans/2026-05-24-research-op-skill.md) — the 7-phase implementation plan
