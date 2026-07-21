<div align="center">

<img src="asset/arc-logo-circle.png" alt="ARC logo" width="1000" />

# Agentic Research Control Panel (ARC)

**Agents run the loop. You govern the research.**

A local control layer for coding agents that run research experiments in real repos,<br />
with approved objectives, visible runs, evidence-backed results, and project memory you can inspect.

[Why ARC?](#why-arc) ·
[Storage Model](#one-managed-root) ·
[Quick Start](#quick-start) ·
[Research Loop](#the-research-loop) ·
[Command Reference](#command-reference)

<br />

<img src="asset/arc-terminal-demo.gif" alt="ARC research workflow terminal demonstration" width="900" />

</div>

<p align="center">
  <img src="asset/readme-control-panel.png"
       alt="Trustworthy Research Pipeline control panel"
       width="95%" />
</p>

<p align="center">
  <sub>A human control surface for project scope, package status, live runs, evidence, results, and decisions.</sub>
</p>

---

## Why ARC?

When a coding agent runs experiment after experiment in a real research repo,
successful execution is only the first requirement. The harder question is
whether the research state still belongs to the project instead of the chat.

| Challenge | Question ARC keeps visible |
| --- | --- |
| 🎯 **Objective drift** | Can you see whether the agent is still bound to the objective, metric, and baseline you approved? |
| 👀 **Run visibility** | Can you inspect an active campaign instead of trusting a later summary? |
| 📎 **Evidence traceability** | Can you trace a reported metric to the command, context, log, and result that produced it? |
| 🧠 **Project memory** | Can the next session reuse what prior work proved or ruled out? |

ARC keeps management state and experimental evidence outside chat memory. The
agent works through typed queries and guarded commands. The human sees the same
research through a browser interface and ratifies changes that alter intent or
terminal conclusions.

## One Managed Root

ARC manages one versioned root per research workspace:

```text
.research/
|-- VERSION
|-- state/
|   |-- events.jsonl
|   |-- current.json
|   |-- migration.json                 # present after an explicit migration
|   `-- notes/<sha256>.md
|-- audit/
|   `-- actions.jsonl
|-- experiments/
|   `-- <package>/<experiment>/<run>/
|       |-- run.json
|       |-- context.json
|       |-- status.json
|       |-- events.jsonl
|       |-- metrics.jsonl
|       |-- log.txt
|       |-- result.json
|       `-- files/, checkpoints, and experiment-specific files
`-- interface/
    |-- index.html
    |-- live.html
    |-- scope.html
    |-- learnings.html
    |-- packages/<package>/
    |   |-- index.html
    |   |-- plan.html
    |   |-- tracker.html
    |   |-- results.html
    |   |-- implementation.html
    |   |-- analysis.html
    |   `-- docs/
    `-- data/
```

The four directories exist because they answer different questions:

| Layer | Owns | Mutability |
| --- | --- | --- |
| `state/` | Ratified intent, package and experiment records, decisions, rules, learnings, and management history | Guarded event writes |
| `audit/` | The outcome of attempted management commands, including rejections | Append-only |
| `experiments/` | What actually ran and the evidence it produced | Run-local, then immutable evidence |
| `interface/` | What a person needs to inspect | Rebuildable projection |

`state/events.jsonl` is the management authority. Run directories are the
execution and evidence authority. `state/current.json` is a rebuildable state
projection. Everything under `interface/` is a human read model.

This storage change does not redesign the browser experience. The existing
dashboard navigation, package pages, modules, tables, and visual layout remain
multi-page and keep their current structure. Only their source and generated
location move under `.research/interface/`.

Agents do not use `interface/` as context, evidence, or authority. They query
state through the bounded command surface and inspect the relevant run files.
If the interface disagrees with state or run evidence, rebuild the interface
from those authorities.

### The only path setting

The default root is `<workspace>/.research`. Set `RESEARCH_ROOT` only when the
managed tree must live elsewhere:

```bash
export RESEARCH_ROOT=/data/my-project/.research
```

Every state, audit, experiment, migration, query, and interface command resolves
the same root. There is no second runtime-data root.
Process-local server metadata is not persisted research data.

## The Research Model

The intent hierarchy is:

```text
Project -> Direction -> Experiment
                         |
                         `-> Run 1, Run 2, ...
```

- **Project** defines the ratified objective and non-negotiable constraints.
- **Direction** defines one approved research strategy under that objective.
- **Experiment** is the only executable specification. Its `spec` owns the
  purpose, configuration reference, gate, and control mode.
- **Package** groups the working records and experiments for a bounded piece of
  research. It is not another Scope level.
- **Run** is one execution attempt against one Experiment.

There is no separate Task entity. Work previously represented as a Task is
represented by `Experiment.spec`, so intent and execution cannot drift across
two competing objects.

## Quick Start

Setup has three parts: install the skills, attach the project protocol, and
initialize or migrate the managed root.

### 1. Install the skills

Symlink the skills from this toolbox checkout. Do not copy them because their
scripts resolve the shared `lib/` code from this repo.

| Agent | Global skill directory | Invocation |
| --- | --- | --- |
| Claude Code | `$HOME/.claude/skills` | `/research-dashboard` |
| Codex | `$HOME/.agents/skills` | `$research-dashboard` |

```bash
cd /path/to/Agentic-Research-Control-Panel
REPO="$(pwd)"
DEST="$HOME/.agents/skills"  # use $HOME/.claude/skills for Claude Code

mkdir -p "$DEST"
for src in "$REPO"/skills/*/; do
  name="$(basename "$src")"
  if [ -e "$DEST/$name" ] && [ ! -L "$DEST/$name" ]; then
    mv "$DEST/$name" "$DEST/$name.bak.$(date +%Y%m%d%H%M%S)"
  fi
  ln -sfn "${src%/}" "$DEST/$name"
done

ls -l "$DEST" | grep research
```

Open a new agent session after installation.

### 2. Attach the protocol

Copy or merge the protocol files into the research workspace. Never overwrite
existing project instructions without reviewing them.

```bash
WORKSPACE=/path/to/your-research-workspace
PIPELINE=/path/to/Agentic-Research-Control-Panel

test -f "$WORKSPACE/AGENTS.md" || cp "$PIPELINE/AGENTS.md" "$WORKSPACE/AGENTS.md"
test -f "$WORKSPACE/CLAUDE.md" || cp "$PIPELINE/CLAUDE.md" "$WORKSPACE/CLAUDE.md"
```

Prepend project-specific objectives, datasets, budgets, and contribution
constraints to the copied protocol.

### 3A. Initialize a greenfield workspace

Use this path only when the workspace has no prior ARC-managed data:

```bash
cd "$PIPELINE"
python3 -m lib.research_state.cli --workspace "$WORKSPACE" init
```

Initialization creates the versioned `.research/` layout. It fails closed when
it detects prior unversioned managed data.

### 3B. Migrate an installed workspace

Do not run `init` over an installed workspace. Inventory first, take a backup,
then migrate explicitly:

```bash
cd "$PIPELINE"
python3 -m lib.research_state.migration --workspace "$WORKSPACE" inventory
python3 -m lib.research_state.migration --workspace "$WORKSPACE" migrate
python3 -m lib.research_state.migration --workspace "$WORKSPACE" check
```

`inventory` is read-only and creates nothing. `migrate` is idempotent, imports
management records, maps former Task records into `Experiment.spec`, copies
terminal run evidence, and publishes `VERSION` only after parity gates pass.
Active runs, missing identities, unsafe paths, and source drift remain explicit
blockers. `check` verifies the sealed migration and copied evidence.

The migration does not delete old managed roots. Archive them outside the
workspace only after `check` reports `"ok": true`, then run `check` once more.

### 4. Build and serve the interface

Run the commands from the toolbox checkout and point them at the managed
workspace:

```bash
cd "$PIPELINE"
python3 skills/research-dashboard/scripts/ensure_dashboard.py \
  --workspace "$WORKSPACE"

python3 -m lib.interface.serve --workspace "$WORKSPACE" ensure \
  --host 127.0.0.1 --port 8904 --max-port 8904 --json
```

Open [http://127.0.0.1:8904/index.html](http://127.0.0.1:8904/index.html).
The server exposes only the generated interface plus narrow read-only run APIs.

Check a previously started server with:

```bash
python3 -m lib.interface.serve --workspace "$WORKSPACE" status --json
```

The interface builder performs an atomic full rebuild. Do not hand-edit files
under `.research/interface/`; the next build will replace them.

## The Research Loop

Each cycle moves through ratified intent, an executable Experiment, a visible
Run, evidence-backed results, a human decision, and reusable project knowledge.

<img src="asset/arc-workflow.png" alt="ARC research workflow" width="1000" />

| Stage | Claude Code | Codex |
| --- | --- | --- |
| Shape a rough idea | `/research-brainstorm` | `$research-brainstorm` |
| Ratify Project, Direction, or Experiment intent | `/research-scope` | `$research-scope` |
| Materialize a bounded package | `/research-package` | `$research-package` |
| Execute and verify an Experiment | `/research-run` | `$research-run` |
| Continue within one approved Direction | `/research-auto` | `$research-auto` |

### 1. Shape and ratify intent

Brainstorming may draft alternatives, but it does not change Scope. Project,
Direction, Experiment, and scope revisions enter Triage first. The agent may
propose them; only explicit human ratification commits them.

Use onboarding when a workspace has no ratified Project objective:

```text
/research-onboard
```

Onboarding proposes the objective and stops for acceptance, rejection, or
revision. It does not start a campaign.

### 2. Materialize a package

After a Direction and its Experiment specs are ratified:

```text
/research-package from-scope <direction-id>
```

The package groups the plan, experiment records, evidence slots, results, and
decisions. Materialization reads committed state only.

### 3. Query bounded context

An agent asks for the smallest state slice required by one package:

```bash
cd "$PIPELINE"
python3 skills/research-op/scripts/research_op.py \
  context <package-id> --workspace "$WORKSPACE"
```

Add `--phase <phase-id>` to narrow the selection further. The response is an
ephemeral query result. It is not written back as a package file and must not
become a second source of truth.

Useful management queries are:

```bash
python3 -m lib.research_state.cli --workspace "$WORKSPACE" \
  show experiment <experiment-id>
python3 -m lib.research_state.cli --workspace "$WORKSPACE" \
  history experiment/<experiment-id>
python3 -m lib.research_state.cli --workspace "$WORKSPACE" \
  audit <command-id>
```

### 4. Launch and inspect a Run

`research-run` owns readiness checks, the launch acknowledgement, monitoring,
result verification, and terminal routing. The underlying launcher is:

```bash
cd "$PIPELINE"
python3 -m lib.experiments.launch \
  --workspace "$WORKSPACE" \
  --package <package-id> \
  --experiment <experiment-id> \
  --cwd "$WORKSPACE" \
  -- python3 train.py
```

At authorization time, the launcher queries current state and writes an
immutable `context.json` beside `run.json`. That frozen context records exactly
what the Run was allowed to use. Later state changes do not rewrite it.

Inspect open runs or one run directory without reading the human interface:

```bash
python3 -m lib.experiments.report --workspace "$WORKSPACE" --open
python3 -m lib.experiments.report \
  --workspace "$WORKSPACE" \
  --run "$RESEARCH_ROOT/experiments/<package>/<experiment>/<run>"
```

If `RESEARCH_ROOT` is unset, replace it in the second command with
`$WORKSPACE/.research`.

### 5. Verify, decide, and learn

A metric becomes a research fact only when its protocol and evidence pass the
declared gate. Terminal adoption, archival, scope changes, and direction changes
remain human decisions. Accepted results and failed methods are written into
typed state so the next context query can retrieve them.

## Human Interface Contract

The interface is intentionally for people:

- It preserves the current dashboard, package-page, module, table, and visual
  layout.
- It is rebuilt from state and run evidence, never edited as authority.
- It may be deleted and regenerated without losing research truth.
- Agents may report its URL, but they do not read it to form context, infer
  status, verify a claim, or choose the next action.
- A stale page is a projection problem, not a reason to mutate HTML.

This boundary keeps the browser optimized for human comprehension while the
agent consumes compact, typed data.

## Human Control Points

- You approve the Project objective before research execution starts.
- You ratify Direction and Experiment intent before it becomes active.
- You can inspect active and recent Runs in the browser.
- You can trace results to frozen context, commands, logs, metrics, and files.
- You decide whether a terminal result is adopted, revised, archived, or
  continued.

ARC can sit beside MLflow, Weights and Biases, DVC, or another experiment
tracker. Those tools may own specialized telemetry or artifacts. ARC owns the
governed connection among intent, execution, evidence, decisions, and project
knowledge.

## Command Reference

| Capability | Primary skill | Durable result |
| --- | --- | --- |
| Initialize or rebuild the human view | `research-dashboard` | `.research/interface/` |
| Establish the first Project objective | `research-onboard` | Proposal, then ratified Project state |
| Explore an uncommitted idea | `research-brainstorm` | Brainstorm record and optional Direction proposal |
| Change approved intent | `research-scope` | Ratified Project, Direction, or Experiment event |
| Create a bounded work unit | `research-package` | Package and Experiment records |
| Execute and verify | `research-run` | Run envelope, evidence, result, and routing decision |
| Run a direction-level campaign | `research-auto` | Campaign state and package cycles |
| Record analysis and rules | `research-analysis` | Typed learning and rule records |
| Apply guarded mutations and queries | `research-op` | State event plus audited outcome |
| Track long experiments | `research-exp-live` | Structured Run status and evidence |
| Register and allocate compute | `research-resource` | Resource and allocation records |

## Status

The versioned EventStore, Triage and ratification gates, package workflow,
immutable Run envelope, result verification, governed learning store, migration
path, and generated multi-page interface are implemented in this toolbox.

## Acknowledgements

The design was informed by prior work on auto-research agents, research skill
systems, and agent workflow methodology. This repo does not vendor those
projects. Its contribution is a governed control layer around agent-assisted
research: approved intent, visible runs, evidence-backed results, human
decisions, and reusable project knowledge.
