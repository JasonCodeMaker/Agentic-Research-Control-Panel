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
|   |-- research.sqlite3              # transactional management authority
|   |-- events.jsonl
|   |-- current.json
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
| `state/` | Ratified intent, package and experiment records, decisions, rules, learnings, and management history | One SQLite transaction per command |
| `audit/` | The outcome of attempted management commands, including rejections | Append-only |
| `experiments/` | What actually ran and the evidence it produced | Run-local, then immutable evidence |
| `interface/` | What a person needs to inspect | Rebuildable projection |

`state/research.sqlite3` is the management authority. One command writes its
event, aggregate versions, current state, idempotency receipt, and terminal
audit outcome in one transaction. `state/events.jsonl`, `state/current.json`,
and `audit/actions.jsonl` are compatibility exports. Run directories remain
the execution and evidence authority. Everything under `interface/` is a human
read model.

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

Every state, audit, experiment, query, and interface command resolves
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
- **Package** is the governed home for one bounded research unit. It begins as
  a non-executable Draft with a full proposal document. One final approval
  ratifies Direction and Experiment Scope and makes that same aggregate Active.
  It is not another Scope level.
- **Run** is one execution attempt against one Experiment.

There is no separate Task entity. Work previously represented as a Task is
represented by `Experiment.spec`, so intent and execution cannot drift across
two competing objects.

## Quick Start

Give the agent two things: the target workspace and whether the setup is for
Codex, Claude Code, or both. `research-init` inspects first, preserves existing
project instructions, initializes the managed root, installs the
skills, builds the interface, and starts the Dashboard Server by default.

### 1. Bootstrap `research-init` once

The setup skill must be discoverable before it can install its siblings. Link
only this skill from the toolbox checkout, then open a new agent session:

| Agent | Bootstrap destination | Invocation |
| --- | --- | --- |
| Claude Code | `$HOME/.claude/skills/research-init` | `/research-init` |
| Codex | `$HOME/.agents/skills/research-init` | `$research-init` |

```bash
PIPELINE=/path/to/Agentic-Research-Control-Panel
mkdir -p "$HOME/.agents/skills"
ln -s "$PIPELINE/skills/research-init" "$HOME/.agents/skills/research-init"
```

Use `$HOME/.claude/skills` instead for Claude Code. If the destination already
contains a real file or directory, stop and review it; setup does not replace
user-owned skill content.

### 2. Ask the agent to set up the workspace

For Codex:

```text
Use $research-init to set up /path/to/my-research-project for Codex.
```

For Claude Code:

```text
Use /research-init to set up /path/to/my-research-project for Claude Code.
```

The agent first reports whether the workspace is `ABSENT`, `CURRENT`, or
`INVALID`. Greenfield setup then runs:

```bash
python3 "$HOME/.agents/skills/research-init/scripts/research_init.py" \
  --workspace /path/to/my-research-project \
  setup --agent codex
```

By default this command starts a new Dashboard Server or reuses the healthy
server already attached to the same workspace. The result explicitly reports
`started` or `reused`, health, URL, host, port, and an SSH forwarding command.
It also reports the exact `stop` command. Use `--no-serve` only for an
explicitly requested headless or CI setup.

### 3. Resolve only the gates that apply

- Existing unmarked `AGENTS.md` or `CLAUDE.md`: inspect the proposed managed
  block, approve the merge, then rerun with `--merge-protocols`. Existing text
  stays intact.
- Legacy `research_html/`, `outputs/`, or an unversioned managed root: stop.
  Automatic migration is unsupported; preserve the data and resolve it manually
  before a fresh setup.
- External `RESEARCH_ROOT`: confirm the resolved path, then use
  `--allow-external-research-root`.
- `INVALID`: stop. Preserve legacy data; repair an unknown version or
  unversioned root explicitly. Setup does not guess.

### 4. Read the completion report

Successful setup ends in one of two states:

- `READY_NO_PROJECT`: setup is healthy; continue with `research-onboard`.
- `READY_WITH_PROJECT`: setup is healthy; continue with `research-brainstorm`
  for a vague direction or `research-scope` for clear intent.

`REPAIR_REQUIRED` means at least one state, protocol, skill, interface, or
Server check failed. The setup report names the failed invariant. Do not
hand-edit `.research/interface/`; it is an atomic projection of managed state.

## The Research Loop

Each cycle moves through ratified intent, an executable Experiment, a visible
Run, evidence-backed results, a human decision, and reusable project knowledge.

<img src="asset/arc-workflow.png" alt="ARC research workflow" width="1000" />

| Stage | Claude Code | Codex |
| --- | --- | --- |
| Create and refine a standalone Brainstorm | `/research-brainstorm` | `$research-brainstorm` |
| Convert, refine, and atomically finalize a Package | `/research-package` | `$research-package` |
| Ratify Project or later independent Scope changes | `/research-scope` | `$research-scope` |
| Execute and verify an Experiment | `/research-run` | `$research-run` |
| Continue within one approved Direction | `/research-auto` | `$research-auto` |

### 1. Establish Project Scope, then refine without approval churn

Project Scope establishes the durable workspace boundary through one onboarding
review and one user authorization. Brainstorming then creates a standalone idea
document. The agent may refine it and materialize its exact revision as a
non-executable `DRAFT / REFINING` Package without asking for a formal approval.
The Brainstorm stays in governed state as provenance, but it leaves the active
Brainstorm list.

After the Draft Package is refined, the agent presents the complete Direction
and selected Experiments as one Scope Bundle. One user authorization commits
the Package, Direction, and Experiments in a single `TransactionCommitted`
event. That event also opens an Execution Lease limited to the Experiments in
the reviewed bundle.

Use onboarding when a workspace has no ratified Project objective:

```text
/research-onboard
```

Onboarding shows the Project charter once and stops for confirmation, revision,
or rejection. It does not start a campaign.

### 2. Finalize and activate the Draft Package

Ask `research-package` to finalize the reviewed Draft. The agent presents the
complete Direction and Experiment set once. Your approval commits the Scope
Bundle and activates the same Package. The transaction preserves the Package id
and proposal document. It does not create a Proposal aggregate or a second
Package.

`from-scope` is a compatibility command for imported or older state where the
Direction and Experiments were already ratified separately. It is not part of
the normal Scope Bundle workflow.

If a design problem is discovered before the first Run, the user may reopen
that same Package as Draft. ARC preserves the proposal and audit history,
detaches the Experiments, and requires a fresh Scope review before reactivation;
it does not pretend the earlier ratification never happened.

The Package groups the plan, experiment records, evidence slots, results, and
decisions. A Draft cannot enter an execution workflow before finalization.

### 3. Query bounded context

An agent asks for the smallest state slice required by one package:

```bash
cd "$PIPELINE"
python3 skills/research-op/scripts/research_op.py \
  context <package-id> --workspace "$WORKSPACE"
```

Add `--phase <phase-id>` to narrow the selection further. The response is an
ephemeral compact packet with a hard 4,000-character budget and explicit
omission counts. Add `--experiment <id>` for one execution target. Use
`--full` only for Draft editing, Run context freezing, or audit. Neither view
is written back as a package file or becomes a second source of truth.

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

`research-run` owns readiness checks, monitoring, result verification, and
terminal routing. A valid Scope Execution Lease authorizes launches for the
ratified Experiment set, so the normal path does not ask for a separate launch
acknowledgement. Imported Packages without a lease retain the older
`LAUNCH_ACK` compatibility check. The underlying launcher is:

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
declared gate. The user then reviews one evidence-backed Package outcome:
`SUCCESS` or `FAIL`. That decision closes the Execution Lease and writes the
Package plus Decision in one transaction. Optional `research-analysis` work may
happen before the outcome or after it. Accepted results and failed methods stay
available to later context queries.

## Human Interface Contract

The interface is intentionally for people:

- It preserves the current dashboard, package-page, module, table, and visual
  layout.
- It is rebuilt from state and run evidence on demand, never edited as authority.
- It may be deleted and regenerated without losing research truth.
- Agents may report its URL, but they do not read it to form context, infer
  status, verify a claim, or choose the next action.
- A stale page is a projection problem, not a reason to mutate HTML.

Management commands do not rebuild the browser tree. The Dashboard checks a
small source marker on the next request and folds any number of intervening
commands into one rebuild.

## Test layers

Use the smallest layer that matches the change:

```bash
python3 -m pytest -q -m core
python3 -m pytest -q -m integration
python3 -m pytest -q -m projection
python3 -m pytest -q -m release
```

`core` covers the main Project, Brainstorm, Package, Scope Bundle, Execution
Lease, and transactional safety paths. Projection and broad static parity
checks stay outside the normal inner loop. A full release run still uses
`python3 -m pytest -q`.

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
| Set up, attach, or repair ARC | `research-init` | Verified setup plus a running Dashboard Server |
| Rebuild or inspect the human view | `research-dashboard` | `.research/interface/` |
| Establish the first Project objective | `research-onboard` | Project review, then one `PROJECT_COMMIT` transaction |
| Explore an uncommitted idea | `research-brainstorm` | Standalone Brainstorm and governed document |
| Change approved intent | `research-scope` | Ratified Project, Direction, or Experiment event |
| Convert or finalize a bounded work unit | `research-package` | Draft Package or one atomic Scope-plus-activation event |
| Execute and verify | `research-run` | Run envelope, evidence, result, and routing decision |
| Run a direction-level campaign | `research-auto` | Campaign state and package cycles |
| Record analysis and rules | `research-analysis` | Typed learning and rule records |
| Apply guarded mutations and queries | `research-op` | State event plus audited outcome |
| Track long experiments | `research-exp-live` | Structured Run status and evidence |
| Register and allocate compute | `research-resource` | Resource and allocation records |

## Status

The versioned transaction kernel, semantic review gates, package workflow,
immutable Run envelope, result verification, governed learning store, and
generated multi-page interface are implemented in this toolbox.

## Acknowledgements

The design was informed by prior work on auto-research agents, research skill
systems, and agent workflow methodology. This repo does not vendor those
projects. Its contribution is a governed control layer around agent-assisted
research: approved intent, visible runs, evidence-backed results, human
decisions, and reusable project knowledge.
