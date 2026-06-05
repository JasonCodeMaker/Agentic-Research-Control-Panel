# Trustworthy Auto-Research Pipeline


> A project-management layer for autonomous ML research. You attach it to a research repo, define the
> objective, and let `/research-auto` advance the work from project setup to scoped tasks, experiments,
> verified results, and project memory — with every claim gated by evidence instead of trust.

This repo is the **toolbox**, not the research project itself. Its skills run from inside the ML project
you want to manage. The agent can propose and execute work; **you own the objective and the
ratification gates**.

**Current maturity, in one sentence.** The dashboard, Scope/Triage system, trust gates, Context Pack,
self-evolution Rule Store, `/research-auto` front door, and deterministic dispatch contract are
implemented and tested; the remaining work is replacing tested fake role adapters with live
model-dispatched scientist roles.

**Contents** · [Why This Exists](#why-this-exists) · [Quick Start](#quick-start) ·
[Research Lifecycle](#research-lifecycle) · [What `/research-auto` Does](#what-research-auto-does) ·
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

1. **The skills** — the 12 `/research-*` commands. Install them once at the **global** scope (visible in
   every project) *or* per-repo at the **project** scope.
2. **The protocols + dashboard** — attached **per research project** you want to manage.

Natural-language paragraphs explain the intent and guardrails. `bash` blocks are exact setup commands.
`text` blocks are slash commands or natural-language instructions.

### Prerequisites

- **Python 3.13** on `PATH`. The skills' helper scripts target it and use only the standard library —
  there is nothing to `pip install`. `pytest` is needed only to run the verification suite in step 2.
- **Node.js** for dashboard JavaScript syntax checks.
- An agent that loads skills from a directory: **Claude Code** (`~/.claude/skills/`) or
  **Codex** (`~/.codex/skills/`).

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
DEST="$HOME/.claude/skills"                     # ← set to your chosen scope from the table above
mkdir -p "$DEST"
for src in "$REPO"/skills/*/; do
  name="$(basename "$src")"
  if [ -e "$DEST/$name" ] && [ ! -L "$DEST/$name" ]; then
    mv "$DEST/$name" "$DEST/$name.bak.$(date +%Y%m%d%H%M%S)"
  fi
  ln -sfn "${src%/}" "$DEST/$name"
done
ls -l "$DEST" | grep research                   # expect 12 symlinks: 'l…' lines with '-> …/skills/<name>'
```

Then reload the agent (restart Claude Code, or open a new session) so it discovers the skills, type
`/research-` and confirm the 12 commands autocomplete.

### 2 · Verify the toolbox

```bash
python3.13 -m pytest tests/                     # expect: 440 passed
```

If `python3.13` is not on `PATH`, use any Python 3.13 interpreter — e.g.
`conda run -n <env> python -m pytest tests/`.

### 3 · Attach the pipeline to a research project

The skills are now callable, but each managed project also needs the operating **protocols**
(`CLAUDE.md` + `WORKFLOW.md`) at its repo root, with your project context prepended above the universal
sections.

```bash
cd /path/to/your-research-project
PIPELINE=/path/to/Trustworthy-Research-Pipeline   # the toolbox repo (the dir holding CLAUDE.md)
mkdir -p outputs/_scope outputs/_selfevolve

test -f CLAUDE.md  || cp "$PIPELINE/CLAUDE.md"  CLAUDE.md
test -f WORKFLOW.md || cp "$PIPELINE/WORKFLOW.md" WORKFLOW.md
```

If either file already exists, keep it and merge the framework protocols instead of overwriting. Add the
project-specific section above the framework protocols:

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
```

Run once per project. This creates `research_html/` — the shared surface where you and the agent read the
same compiled state (lanes, Scope projection, package links, Context Pack).

### 5 · Onboard or define the project objective, then run the loop

The project's **global objective** is the first thing that must be locked in: `/research-auto` refuses to
run experiments until a Project node is ratified, so on a fresh project its very first action is to
propose that objective and stop for you. After the dashboard exists, pick the entry point that matches
how much project context already exists:

| Entry point | Use when | What it does |
| --- | --- | --- |
| `/research-onboard` | **Recommended for an existing research repo.** The project already has README / configs / source / data notes / baselines, but no committed Project node. | Analyzes the workspace, writes `outputs/_scope/prior_knowledge.md`, drafts a Project objective, submits it as a pending Triage proposal, then stops for your ratification. |
| `/research-scope` | You already know the exact Project objective and want to author it directly. | Builds a typed Project proposal for the Scope SSOT admission gate. |
| `/research-auto` | You want the front door to choose the next legal setup/run action. | Detects dashboard / Project / Direction / Task / package readiness and returns the next proposal or run action. |

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

Only a ratified objective is committed to the Scope SSOT (`outputs/_scope/transitions.jsonl`); the
framework never ratifies silently or materializes a package from a pending proposal. After each accepted
proposal, run `/research-auto` again — the same command intentionally advances one legal step at a time
(**objective → Direction → Task → run**). `/research-package` can also be driven directly to materialize
a package, but only from committed Scope state.

---

## Research Lifecycle

The pipeline is easiest to understand as a research project lifecycle. Each phase has a clear input, user
decision, agent action, and durable output.

| Phase | Operator action | Framework action | Durable output |
| --- | --- | --- | --- |
| **0 · Attach toolbox** | Install skills and attach protocols to the target repo. | Symlinks skills, preserves/merges protocol files, and verifies the toolbox. | The target repo now has the operating rules. |
| **1 · Initialize workspace** | Run `/research-dashboard`, then `/research-onboard` if no Project node exists. | Scaffolds the live dashboard; for existing repos, analyzes project context into a prior-knowledge digest and Project proposal. | `research_html/`, optional `outputs/_scope/prior_knowledge.md`, dashboard lanes. |
| **2 · Ratify project objective** | Inspect and approve/reject the `/research-onboard`, `/research-scope`, or `/research-auto` Project proposal. | Proposes a Project node through Triage; commits only after human ratification. | Accepted Project in Scope SSOT, or a rejected proposal record. |
| **3 · Form a research direction** | Approve/reject the Direction proposal in chat. | Uses literature/ideation/ranking capability to shape a Direction with a typed yardstick. | Direction node with hypothesis, metric, baselines, success predicate. |
| **4 · Create an executable task** | Approve/reject the Task proposal; optionally lower the autonomy dial. | Proposes a Task with experiment/config/gate predicate. Default dial is `autonomous`. | Task node and, once committed, a materialized package. |
| **5 · Execute the research loop** | Run `/research-auto`; supervise according to the dial. | Loads context, reads papers, proposes ideas, runs experiments, verifies evidence, records memory. | Runtime artifacts, audit log, verdicts, package state updates. |
| **6 · Decide the outcome** | Review dashboard/PACK/verdict in chat; approve terminal decisions or scope changes. | Files Triage proposals when goals should change; never edits the objective silently. | Success/fail/archive state, or a versioned Scope revision. |
| **7 · Learn for the next cycle** | Run `/research-reflect`, then approve `/research-apply` for accepted lessons. | Mines audit logs for recurring failures and proposes rules. | Active project rules exported into the Context Pack. |

**Completion means:** one research package reaches a terminal, evidence-backed state: success, fail, or
archive. A success is not a self-declared win; it is a package whose metric/verifier gates clear against
the committed Scope yardstick.

---

## What `/research-auto` Does

After dashboard init and Project onboarding, `/research-auto` is the command to try for continuing the
loop. It runs a front-door admission check before attempting experiments:

| State | Condition | What happens |
| --- | --- | --- |
| **A** | Dashboard missing | Stops and tells you to run `/research-dashboard`. |
| **B** | No committed Project | Proposes a Project objective through Triage; waits for you. |
| **C** | Project exists, no Direction | Forms and proposes a Direction; waits for you. |
| **D** | Direction exists, no Task | Proposes a Task with default `autonomous` dial; waits for you. |
| **E** | Direction+Task committed, no package | Returns the materialize-package action from committed Scope only. |
| **F** | Package exists, readiness incomplete | Runs readiness at the selected dial; repairs or stops before unattended work. |
| **G** | Project+Direction+Task+package ready | Enters the production loop. |

The boundary is deliberate:

- `/research-auto` may **propose** Project, Direction, and Task nodes.
- You accept or reject those proposals in chat.
- The agent may run the mechanical Triage/Scope commands only after your explicit ratification.
- A package may be materialized only from committed Scope state, never from a pending proposal.

What is live today: this front door, the A-G admission state machine, and the deterministic trust
contract are implemented and tested. The production loop has a tested dispatch seam and gate wiring; the
remaining maturation work is connecting live model-dispatched role adapters for the full unattended
scientist loop.

### The autonomy dial

The dial controls how often the agent pauses for acknowledgement. It does **not** weaken correctness gates.
New Task proposals default to `autonomous`, but `/research-auto` surfaces all four choices before you
accept the proposal.

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
| `research_html/` | Live dashboard: lanes, context page, Scope projection, package links. |
| `outputs/_scope/transitions.jsonl` | Canonical Scope SSOT transition log. |
| `outputs/_scope/triage.jsonl` | Pending and disposed objective proposals. |
| `outputs/<pkg>/` | Per-package runtime records, audit logs, Context Pack, experiment artifacts. |
| `outputs/_selfevolve/` | Governed self-learning memory. |

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
├── CLAUDE.md        # agent operating protocols (merged into the target research repo)
├── WORKFLOW.md      # the 7-step in-package controller the agent obeys
├── skills/          # 12 composing skills — the toolbox the agent installs
├── lib/             # 6 passive validators / stores (scope_ssot, verifier, cite_check, …)
├── tests/           # pytest suite (440 passing)
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
| `research-auto` | Post-init front door plus orchestrator. |
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
| `lib/context_pack` | Deterministic project-memory projection. |
| `lib/self_evolve` | Governed project self-learning memory. |

---

## Contributing

This is a research codebase; the bar is traceability and tests, not ceremony.

- **Design before code.** New behavior is brainstormed and planned before any implementation.
- **Test-Driven, always.** Every change ships with tests, and the agent should keep the full Python 3.13
  pytest suite green (440 passing).
- **One mutation surface.** Package HTML is edited only through `research-op`; direct `Edit`/`Write` on a
  package surface is a workflow violation.
- **Surgical changes.** Touch only what the task needs and match the existing style; do not rewrite the
  project-agnostic protocol bodies in `CLAUDE.md` / `WORKFLOW.md` — prepend, don't replace.

The full operating contract is in [`CLAUDE.md`](CLAUDE.md).

## Acknowledgements

The design was informed by — but does not vendor — prior art studied as references:
[ARIS · Auto-claude-code-research-in-sleep](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep),
[academic-research-skills](https://github.com/Imbad0202/academic-research-skills), and the Superpowers
skill methodology. They were studied, not imported — this pipeline's trust contracts are its own.
