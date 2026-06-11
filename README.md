# Trustworthy Auto-Research Pipeline


> A project-management layer for autonomous ML research. You attach it to a research repo, define the
> objective, form a scoped package, and let `/research-run` complete that package through experiments,
> verified results, and project memory — with every claim gated by evidence instead of trust.

This repo is the **toolbox**, not the research project itself. Its skills run from inside the ML project
you want to manage. The agent can propose and execute work; **you own the objective and the
ratification gates**.

**Current maturity, in one sentence.** The dashboard, Scope/Triage system, trust gates, Context Pack,
self-evolution Rule Store, `/research-run` package runner, exp-live runtime envelope, fact-backed package
surfaces, and deterministic dispatch contract are implemented and tested; `/research-auto` remains only a
deprecated compatibility alias.

**Contents** · [Why This Exists](#why-this-exists) · [Quick Start](#quick-start) ·
[Research Lifecycle](#research-lifecycle) · [What `/research-run` Does](#what-research-run-does) ·
[Trust Guarantees](#trust-guarantees) · [How It Works](#how-it-works) ·
[Repository Layout](#repository-layout) · [Reference](#reference) · [Contributing](#contributing)

---

## Why This Exists

Autonomous research agents tend to fail in three specific ways, and this pipeline is built to prevent
each one:

| # | Failure mode | What the pipeline does about it |
| --- | --- | --- |
| **1** | **Context pollution + hallucination** lead the agent to deceive or ignore instructions. | Typed interfaces, multi-agent context isolation, mandatory Test-Driven implementation, and a deliberately small workflow surface. |
| **2** | **No HCI alignment** between the model's working context and the user's. | A live, real-time HTML dashboard where the user and the agent read the same compiled state. |
| **3** | **No personalized project self-learning.** | A governed rule store, a self-reflection loop, and durable project memory (the Context Pack). |

Every capability in this repo traces back to one of these three problems; the
[trust guarantees](#trust-guarantees) below are how they are enforced in code rather than promised in
prose.

---

## Quick Start

Setup installs **two things at two scopes**:

1. **The skills** — the `/research-*` commands. Install them once at the **global** scope (visible in every
   project) *or* per-repo at the **project** scope.
2. **The protocols + dashboard** — attached **per research project** you want to manage.

Natural-language paragraphs explain the intent and guardrails. `bash` blocks are exact setup commands.
`text` blocks are slash commands or natural-language instructions.

### Prerequisites

- **Python 3.13** on `PATH`. The skills' helper scripts target it and use only the standard library —
  there is nothing to `pip install`. `pytest` is needed only to run the verification suite in step 2.
- **Node.js 22+** for dashboard JavaScript syntax checks and direct execution of `workflow.ts`.
- An agent that loads skills from a directory: **Claude Code** (`~/.claude/skills/`) or
  **Codex** (`~/.codex/skills/`, with `AGENTS.md` at the project root).

### 1 · Install the skills (symlink — never copy)

Each skill's helper scripts resolve the shared `lib/` *relative to this repo*, so the skills must be
**symlinked** into the skills directory. A plain copy placed outside the repo cannot find `lib/` and will
fail at runtime. Pick a scope by setting `DEST`:

| Scope | `DEST` value | Skills become visible in |
| --- | --- | --- |
| **Global** (recommended) | `$HOME/.claude/skills` | every project on this machine |
| **Project** | `/path/to/your-project/.claude/skills` | that one repo only |
| Codex (global) | `$HOME/.codex/skills` | every project on this machine |

Run from the toolbox repo root, after setting `DEST` to your chosen scope:

```bash
cd /path/to/Trustworthy-Research-Pipeline      # the toolbox repo (the dir holding skills/ and lib/)
REPO="$(pwd)"
DEST="$HOME/.claude/skills"                     # Claude Code; use "$HOME/.codex/skills" for Codex
mkdir -p "$DEST"
for src in "$REPO"/skills/*/; do
  name="$(basename "$src")"
  if [ -e "$DEST/$name" ] && [ ! -L "$DEST/$name" ]; then
    mv "$DEST/$name" "$DEST/$name.bak.$(date +%Y%m%d%H%M%S)"
  fi
  ln -sfn "${src%/}" "$DEST/$name"
done
ls -l "$DEST" | grep research                   # expect research symlinks: 'l…' lines with '-> …/skills/<name>'
```

Then reload the agent (restart Claude Code, or open a new Codex session) so it discovers the skills,
type `/research-` and confirm the commands autocomplete.

When a protocol or skill body shows a script path like `skills/<name>/scripts/...` from inside a managed
research repo, resolve it through the installed symlink directory, e.g.
`$HOME/.codex/skills/<name>/scripts/...` for Codex or `$HOME/.claude/skills/<name>/scripts/...` for
Claude Code. Do not copy the toolbox into the target repo just to make relative script examples work.

### 2 · Verify the toolbox

```bash
python3.13 -m pytest tests/                     # expect a passing suite
```

If `python3.13` is not on `PATH`, use any Python 3.13 interpreter — e.g.
`conda run -n <env> python -m pytest tests/`.

### 3 · Attach the pipeline to a research project

The skills are now callable, but each managed project also needs the operating **protocols**
(`AGENTS.md` for Codex and `CLAUDE.md` for Claude Code / shared protocol text) at its repo root, with
your project context prepended above the universal sections. The package controller stays in the toolbox
as executable TypeScript (`workflow.ts`) and is called through the installed skills.

```bash
cd /path/to/your-research-project
PIPELINE=/path/to/Trustworthy-Research-Pipeline   # the toolbox repo (the dir holding AGENTS.md)
mkdir -p outputs/_scope outputs/_selfevolve

test -f AGENTS.md || cp "$PIPELINE/AGENTS.md" AGENTS.md
test -f CLAUDE.md  || cp "$PIPELINE/CLAUDE.md"  CLAUDE.md
```

If any file already exists, keep it and merge the framework protocols instead of overwriting. `AGENTS.md`
is the Codex adapter; `CLAUDE.md` remains the full shared operating contract. Add the project-specific
section above the framework protocols:

- project name and objective;
- datasets, baselines, metrics, and success criteria;
- compute constraints and available machines;
- non-goals, safety constraints, or reviewer concerns.

### 4 · Initialize the shared dashboard

Run:

```text
/research-dashboard
```

For transparent setup, this command scaffolds and validates the dashboard with:

```bash
cd /path/to/your-research-project
PIPELINE=/path/to/Trustworthy-Research-Pipeline
python3.13 "$PIPELINE/skills/research-dashboard/scripts/ensure_dashboard.py" --root research_html
node --check research_html/assets/research.js
node --check research_html/data/research-packages.js
test -f research_html/index.html
test -f research_html/live.html
```

Run once per project. This creates `research_html/` — the shared surface where you and the agent read the
same compiled state (lanes, Scope projection, package links, Context Pack, and the Live Runs page).

### 5 · Onboard, form a package, then run it

The project's **global objective** is the first thing that must be locked in. `/research-run` will not run
experiments until Project, Direction, Task, and package surfaces already exist, so use the formation
commands first:

| Entry point | Use when | What it does |
| --- | --- | --- |
| `/research-onboard` | **Recommended for an existing research repo.** The project already has README / configs / source / data notes / baselines, but no committed Project node. | Analyzes the workspace, writes `outputs/_scope/prior_knowledge.md`, drafts a Project objective, submits it as a pending Triage proposal, then stops for your ratification. |
| `/research-brainstorm` | You have a vague or partial research idea. | Shapes pre-package ideas, grounds them with literature when needed, and proposes one Direction through Triage. |
| `/research-scope` | You already know the exact Project/Direction/Task scope or need to revise it. | Builds typed Scope proposals and validation milestones for the Scope SSOT admission gate. |
| `/research-package` | Direction and Task are committed, but no package exists yet. | Materializes package surfaces from committed Scope state only. |
| `/research-run` | A scoped package exists and should be executed to completion. | Runs readiness, implementation/review, launch/monitoring, artifact propagation, result verification, and terminal routing. |

For an **existing project**, the normal setup path is:

```text
/research-onboard
```

The onboarder reads the project content it finds (typically `README.md`, `CLAUDE.md`, configs, source
tree, dataset notes, baselines, or reported metrics), writes a compact prior-knowledge digest for later
roles, and proposes a Project node through Triage. It does **not** commit the Scope SSOT and does not
create a package. Inspect the proposal in chat, then accept/reject/revise it:

Unlike the scaffolding in steps 3–4, this is **interactive, not a one-shot command**: the framework only
*proposes* (the proposal lands as a pending Triage item), and you ratify in chat — you never hand-write
Scope entries:

```text
Accept this proposal.
Reject this proposal because …
Revise the objective / Direction to focus on …
Use the supervised / checkpoints / async / autonomous autonomy level for this Task.
```

Only ratified scope is committed to the Scope SSOT (`outputs/_scope/transitions.jsonl`); the framework
never ratifies silently or materializes a package from a pending proposal. The normal path is:
`/research-onboard` or `/research-scope` for Project, `/research-brainstorm` or `/research-scope` for
Direction, `/research-scope` for Task milestones, `/research-package` for package materialization, then
`/research-run` to complete the package.

---

## Research Lifecycle

The pipeline is easiest to understand as a research project lifecycle. Each phase has a clear input, user
decision, agent action, and durable output.

| Phase | Operator action | Framework action | Durable output |
| --- | --- | --- | --- |
| **0 · Attach toolbox** | Install skills and attach protocols to the target repo. | Symlinks skills, preserves/merges protocol files, and verifies the toolbox. | The target repo now has the operating rules. |
| **1 · Initialize workspace** | Run `/research-dashboard`, then `/research-onboard` if no Project node exists. | Scaffolds the live dashboard; for existing repos, analyzes project context into a prior-knowledge digest and Project proposal. | `research_html/`, optional `outputs/_scope/prior_knowledge.md`, dashboard lanes. |
| **2 · Ratify project objective** | Inspect and approve/reject the `/research-onboard` or `/research-scope` Project proposal. | Proposes a Project node through Triage; commits only after human ratification. | Accepted Project in Scope SSOT, or a rejected proposal record. |
| **3 · Form a research direction** | Approve/reject the Direction proposal in chat. | Uses literature/ideation/ranking capability to shape a Direction with a typed yardstick. | Direction node with hypothesis, metric, baselines, success predicate. |
| **4 · Create an executable task** | Approve/reject the Task proposal; optionally lower the autonomy dial. | Proposes a Task with experiment/config/gate predicate. Default dial is `autonomous`. | Task node and, once committed, a materialized package. |
| **5 · Execute the research package** | Run `/research-run`; supervise according to the dial. | Loads context, runs readiness, implements/reviews if needed, launches and monitors experiments, propagates artifacts, verifies results, and routes the package until terminal. | Runtime artifacts, audit log, verdicts, package state updates. |
| **6 · Decide the outcome** | Review dashboard/PACK/verdict in chat; approve terminal decisions or scope changes. | Files Triage proposals when goals should change; never edits the objective silently. | Success/fail/archive state, or a versioned Scope revision. |
| **7 · Learn for the next cycle** | Run `/research-reflect`, then approve `/research-apply` for accepted lessons. | Mines audit logs for recurring failures and proposes rules. | Active project rules exported into the Context Pack. |

**Completion means:** one research package reaches a terminal, evidence-backed state: success, fail, or
archive. A success is not a self-declared win; it is a package whose metric/verifier gates clear against
the committed Scope yardstick.

During day-to-day use, the runtime and fact storage appear through the same surfaces you already read:

| Surface you use | What it shows | What to trust |
| --- | --- | --- |
| `research_html/live.html` | Open, stale, failed, and recent terminal wrapper-launched runs. | It reads runtime files first, so use it before raw tmux scrollback for routine status. |
| Package `tracker.html` | Live checks, resource allocation, runtime roots, and log paths. | For fact-backed packages, repeated tracker rows come from `live_checks.csv` and `resource_allocation.csv`. |
| Package `results.html` | Result gates, result tables, headline metrics, and verdict support. | Repeated result values should point back to the same CSV row id. |
| Dashboard `methodsTried[]` | The compact method/result summary shown on package cards and lint surfaces. | For fact-backed packages, it is a compatibility projection from `methods_tried.csv`. |
| `research-op check --scope fact-alignment` | Missing sources, stale projections, manual PASS rows, and migration state. | Treat errors here as evidence that a page or registry view no longer matches its fact source. |

Legacy packages still work. A package becomes fact-backed only when
`research_html/data/packages/<pkg>/` exists. Until then, the dashboard can continue reading old HTML and
registry fields as compatibility inputs.

---

## What `/research-run` Does

After dashboard init, Scope ratification, Task creation, and package materialization, `/research-run` is
the command to execute the package. It runs an admission check before attempting experiments:

| State | Condition | What happens |
| --- | --- | --- |
| **A** | Dashboard missing | Stops and tells you to run `/research-dashboard`. |
| **B** | No committed Project | Hands off to `/research-onboard` or `/research-scope`. |
| **C** | Project exists, no Direction | Hands off to `/research-brainstorm` or `/research-scope`. |
| **D** | Direction exists, no Task | Hands off to `/research-scope` milestone planning. |
| **E** | Direction+Task committed, no package | Hands off to `/research-package`. |
| **F** | Package exists, readiness incomplete | Runs readiness at the selected dial; repairs or stops before unattended work. |
| **G** | Project+Direction+Task+package ready | Enters the package execution loop. |

The boundary is deliberate:

- `/research-run` does **not** propose Project, Direction, or Task nodes.
- `/research-run` does **not** materialize packages.
- `/research-run` completes an existing package by executing its current task spine and routing every
  package mutation through `research-op`.
- Scope changes discovered during execution are handed back to `/research-scope`; they are never silently
  written by the run loop.

What is live today: this admission state machine, the deterministic dispatch contract, `research-exp-live`
runtime envelope, and fact-backed package surfaces are implemented and tested.

### The autonomy dial

The dial controls how often the agent pauses for acknowledgement. It does **not** weaken correctness gates.
Task proposals set the dial in Scope; `/research-run` reads that dial when deciding readiness and PACK
requirements.

| Level | Agent pauses for you at | Extra expectation |
| --- | --- | --- |
| `supervised` | Every gate. | Maximum interaction. |
| `checkpoints` | Terminal checkpoints. | Fewer interruptions. |
| `async` | No routine pauses. | PACK narrative must be maintained. |
| `autonomous` | No routine pauses. | PACK narrative plus stronger independent verification. |

If a Project or Direction scope change invalidates downstream assumptions, affected Tasks auto-revert to
`supervised` and lock until re-grounded.

---

## Trust Guarantees

The contribution is the trust record, not just the agent loop.

- **Reject-before-write.** Package surfaces are mutated through `research-op`; invalid writes are rejected
  before touching disk and logged.
- **User-owned objective.** Intent lives in the versioned Scope SSOT. The agent proposes; the user
  ratifies.
- **No fabricated citations.** A citation must resolve to a fetched source before it reaches the record.
- **No self-graded success.** Verdicts are checked against the committed success predicate, with
  producer/judge separation.
- **Independent ranking.** Idea ranking is scored by independent sub-agents; the proposer does not rank
  its own work.
- **Human-gated self-learning.** Reflection can propose rules, but only `research-apply` can land them
  with approval and a clearing verdict.
- **Shared project memory.** The Context Pack is a deterministic projection of project knowledge, so the
  agent and user read the same compiled context.

---

## How It Works

### Main artifacts

| Artifact | Meaning |
| --- | --- |
| `research_html/` | Live dashboard: lanes, context page, Scope projection, package links, Live Runs page. |
| `research_html/data/research-packages.js` | Dashboard registry: package cards, status, task spine, and compatibility projections. |
| `research_html/data/rules.js` | Unified rules registry: every binding rule as one typed row (`universal` R/T mirror · `project` · `package`); mutated only via `research-op --target rule`. |
| `research_html/data/packages/<pkg>.facts.js` | Package content facts and page projection metadata for fact-backed packages. |
| `research_html/data/packages/<pkg>/tables/*.csv` | Canonical package table facts: result gates, result tables, tracker live checks, resource allocation, and methods tried. |
| `outputs/_scope/transitions.jsonl` | Canonical Scope SSOT transition log. |
| `outputs/_scope/triage.jsonl` | Pending and disposed objective proposals. |
| `outputs/_live/runs.jsonl` | Global index of wrapper-launched experiment runs. |
| `outputs/<pkg>/` | Per-package runtime records, audit logs, Context Pack, experiment artifacts. |
| `outputs/<pkg>/runs/<run_id>/status.json` | Raw live-run state for wrapper-launched experiments. |
| `outputs/_selfevolve/` | Governed self-learning memory. |

### Data storage architecture

The fact-backed path separates raw evidence, canonical facts, and rendered pages:

```text
outputs/<pkg>/
  runs/<run_id>/
    status.json          # raw live-run truth for wrapper-launched runs
    events.jsonl         # parsed metrics, progress, phases, anomalies
    log.txt              # bounded raw log fallback
  _actions.jsonl         # research-op audit trail
  context_pack.md        # package memory projection

outputs/_live/
  runs.jsonl             # global run launch/terminal index

research_html/data/
  research-packages.js   # dashboard registry and compatibility projections
  rules.js               # unified rules registry (universal mirror + project + package rows)
  packages/
    <pkg>.facts.js       # content facts and projection revisions
    <pkg>/
      tables/
        result_gate.csv
        result_table_<exp_id>.csv
        live_checks.csv
        resource_allocation.csv
        methods_tried.csv
      extractors/
        <exp_id>.json

research_html/packages/<pkg>/
  results.html           # projection from result facts
  tracker.html           # projection from tracker facts
  index.html / plan.html / analysis.html / docs/
```

The authority order is:

1. Runtime artifacts under `outputs/<pkg>/...` are raw experimental evidence.
2. Extractors and `research-op` convert evidence or accepted user actions into JS/CSV facts.
3. `research_html/data/packages/<pkg>.facts.js` stores repeated content facts and page projection metadata.
4. CSV files store repeated table facts.
5. HTML pages render those facts; for fact-backed sections, HTML is not the source of truth.

`outputs/_scope/transitions.jsonl` remains the Scope SSOT, and
`outputs/<pkg>/runs/<run_id>/status.json` remains the live-run source. The package fact layer does not
replace either one; it stores package-surface facts derived from them.

Useful commands:

```bash
python skills/research-package/scripts/render_package_projection.py --pkg <id> --page all
python skills/research-dashboard/assets/dashboard/scripts/audit_fact_migration.py --pkg <id>
python skills/research-op/scripts/research_op.py --pkg <id> --op check --scope fact-alignment
```

### Skill layering and the Mutation Rule

The surfaces are scaffolded once, then mutated through a single door:

```text
research-dashboard  (once/project)  -> scaffolds research_html/
research-package    (once/package)  -> scaffolds one direction package
research-analysis   (mid-frequency) -> writes Rules + Insights
research-op         (every write)   -> validates and logs all mutations
```

**The Mutation Rule:** after scaffolding, every edit to a package surface routes through `research-op`.
Direct edits to package HTML are workflow violations. `research-op` enforces the state matrix, target
invariants, and append-only audit trail.

### State model

Each package sits in a legal `(category, status)` state. The dashboard has four lanes:

- **brainstorm** for pre-package ideas;
- **in-progress** for active packages;
- **success** for acquitted packages;
- **fail** for negative or blocked outcomes.

Brainstorm ideas are not Scope nodes. A Direction/Task becomes durable only after the Triage proposal is
accepted and committed into the Scope SSOT.

### Context Pack

The Context Pack is the project's compiled memory. It contains active rules, failed methods, adopted
wins, fetched papers, gaps, and the active yardstick. It is deterministic and read-only:

- agent face: `outputs/<pkg>/context_pack.md`;
- human face: `research_html/context.html`;
- durable core: `research_html/data/context-core.js`.

It never lands a rule by itself. Rules are proposed by reflection and landed only through the governed
apply path.

### Self-evolution memory

Self-learning has two stores:

| Store | What it holds | Lifecycle |
| --- | --- | --- |
| **Rule Store** | Anti-regression lessons and advisory project rules. | Live, in-band. |
| **Skill Store** | Generated executable skills. | Built and tested, but gated/off by default. |

A rule moves through:

```text
observed -> candidate -> validating -> provisional -> active
                                      -> superseded / invalidated / archived_reopenable
```

Only active rules enter the Context Pack. Aging lowers retrieval priority; it does not silently delete
rules.

---

## Repository Layout

```text
Trustworthy-Research-Pipeline/
├── README.md        ← you are here
├── AGENTS.md        # Codex adapter for this toolbox and consuming projects
├── CLAUDE.md        # agent operating protocols (merged into the target research repo)
├── workflow.ts  # executable in-package controller and run-ticket CLI
├── skills/          # composing skills — the toolbox the agent installs
├── lib/             # validators, stores, runtime helpers, and fact helpers
├── tests/           # pytest suite
└── docs/            # design notes
```

---


## Reference

### Skills

| Skill | Role |
| --- | --- |
| `research-dashboard` | Project-level dashboard scaffold. |
| `research-onboard` | Empty-workspace skeleton or existing-repo analysis into a Project proposal. |
| `research-brainstorm` | Explicit escape hatch for pre-package idea exploration. |
| `research-scope` | Scope SSOT and Triage admission gate. |
| `research-package` | Package scaffold materialized from committed Scope. |
| `research-run` | Package execution controller; completes an existing scoped package. |
| `research-auto` | Deprecated compatibility alias for `research-run`. |
| `research-exp-live` | Structured launch/monitor/resume envelope for long-running experiment commands. |
| `research-lit` | Literature/source gathering role. |
| `research-ideate` | Idea generation and refinement role. |
| `research-analysis` | Per-package Rules + Insights page. |
| `research-op` | Single mutation surface: validate, reject-before-write, audit. |
| `research-reflect` | Read-only self-learning proposer. |
| `research-apply` | Human-gated self-learning applier. |

### Libraries

| Library | Role |
| --- | --- |
| `lib/scope_ssot` | Versioned intent store: Project -> Direction -> Task. |
| `lib/verifier` | Cross-model jury and independence table. |
| `lib/cite_check` | Fetch-don't-fabricate citation gate. |
| `lib/ranking` | Independent multi-agent ranking. |
| `lib/exp_live` | Runtime envelope for wrapper-launched experiment commands. |
| `lib/package_facts` | JS/CSV fact helpers and projection freshness checks. |
| `lib/context_pack` | Deterministic project-memory projection. |
| `lib/self_evolve` | Governed project self-learning memory. |

---

## Contributing

This is a research codebase; the bar is traceability and tests, not ceremony.

- **Design before code.** New behavior is brainstormed and planned before any implementation.
- **Test-Driven, always.** Every change ships with tests, and the agent should keep the full Python 3.13
  pytest suite green.
- **One mutation surface.** Package HTML is edited only through `research-op`; direct `Edit`/`Write` on a
  package surface is a workflow violation.
- **Surgical changes.** Touch only what the task needs and match the existing style; do not rewrite the
  project-agnostic protocol bodies in `AGENTS.md` / `CLAUDE.md` — prepend, don't replace.

The full operating contract is in [`CLAUDE.md`](CLAUDE.md).

## Acknowledgements

The design was informed by — but does not vendor — prior art studied as references:
[ARIS · Auto-claude-code-research-in-sleep](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep),
[academic-research-skills](https://github.com/Imbad0202/academic-research-skills), and the Superpowers
skill methodology. They were studied, not imported — this pipeline's trust contracts are its own.
