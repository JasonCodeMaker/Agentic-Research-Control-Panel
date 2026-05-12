# Trustworthy Research Pipeline

A research workflow scaffold for Claude Code / Codex. It ships two skills that build a per-project HTML dashboard and per-direction research packages, a `WORKFLOW.md` that the agent follows when implementing each package, and a `CLAUDE.md` that distills the five protocols the agent obeys across every project.

## What's in this repo

| File / dir | What it is |
| --- | --- |
| `skills/research-dashboard/` | Skill that scaffolds the project-level `research_html/` dashboard (lanes, schema, learnings page, lint tool). |
| `skills/research-package/` | Skill that scaffolds one research package under `research_html/packages/<YYYY-MM-DD-slug>/` with overview / plan / implementation / results / next-action / tracker / brainstorm pages. |
| `WORKFLOW.md` | Seven-step controller the agent follows inside any package. |
| `CLAUDE.md` | Project-agnostic agent operating context: the five protocols (Workflow, Output Contract, Fact Propagation, Learnings Update, Refinement Guardrails) and the `(category, status)` state model. Consuming projects prepend their own specifics. |

## Installation

### 1. Install the skills

Copy (or symlink) the two skills into your agent's skills directory.

**Claude Code:**

```bash
cp -r skills/research-dashboard ~/.claude/skills/
cp -r skills/research-package   ~/.claude/skills/
```

**Codex:**

```bash
cp -r skills/research-dashboard ~/.codex/skills/
cp -r skills/research-package   ~/.codex/skills/
```

Restart the agent so the new skills are picked up.

### 2. Install the agent operating context

Copy `CLAUDE.md` to your research project's repo root, then prepend project-specific sections (project name, motivation, optimization objective, contribution spine, current best) above the protocols. The protocols themselves are universal — do not edit them per project.

```bash
cp CLAUDE.md /path/to/your-research-project/CLAUDE.md
```

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

### 5. Implement the package using `WORKFLOW.md`

Point the agent at [WORKFLOW.md](WORKFLOW.md) when working inside a package. It defines the decision-owner protocol, subagent dispatch rules, and the read / authority order the agent must follow.

## State model and learnings tooling

Every package carries a `status` field whose legal values depend on its lane:

| category | legal `status` values |
| --- | --- |
| brainstorm | `EXPLORING`, `PILOT_READY`, `PROMOTED`, `ABANDONED` |
| in-progress | `CONTEXT_LOADED`, `IMPLEMENTING`, `IMPLEMENTATION_REVIEW`, `READY_TO_LAUNCH`, `EXPERIMENT_RUNNING`, `LIVE_ANALYSIS`, `RESULT_ANALYSIS`, `NEXT_ACTION_READY`, `BLOCKED` |
| success | `ADOPTED_PENDING_ACK`, `ADOPTED`, `SUPERSEDED` |
| fail | `ARCHIVED`, `ARCHIVED_REOPENABLE` |

Required field sets per `(category, status)` and the structured `methodsTried` row shape are declared in `research_html/data/schema.js`. The Stop Gate of every learnings-relevant turn requires:

```bash
python research_html/scripts/learnings_lint.py all
```

to exit 0. See the **Learnings Update Protocol** section of [CLAUDE.md](CLAUDE.md) for the full event-trigger × lint-gate × atomic-turn contract.
