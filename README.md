<div align="center">

<img src="asset/arc-logo-circle.png" alt="ARC logo" width="1000" />

# Agentic Research Control Panel (ARC)

**Agents run the loop. You govern the research.**

A local control layer for coding agents that run research experiments in real repos,<br />
with approved objectives, visible runs, evidence-backed results, and project memory you can inspect.

[Why ARC?](#why-arc) ·
[Research Loop](#the-research-loop) ·
[Quick Start](#quick-start) ·
[Example Run](#a-complete-example-run) ·
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
  <sub>A shared control surface for project scope, package status, live runs, evidence, results, and human decisions.</sub>
</p>

---

## Why ARC?

When a coding agent runs experiment after experiment in a real research repo,
the code may execute just fine. The harder question is whether the research
state still belongs to the project instead of the chat.

| Challenge | Question ARC keeps visible |
| --- | --- |
| 🎯 **Objective drift** | Several sessions in, can you see whether the agent is still bound to the objective, metric, and baseline you approved? |
| 👀 **Run visibility** | While an auto-research pipeline is executing, can you inspect what it is doing instead of trusting its summary? |
| 📎 **Evidence traceability** | When it reports a metric, can you trace that number to an artifact and verify that the result is real and reproducible? |
| 🧠 **Project memory** | Can the next session inherit what this run proved or ruled out? |

Chat is the wrong source of truth for research work. This project keeps the
working state in the repo, where the human and the agent can inspect the same
objective, run state, evidence, result, and decision.

Start from an empty workspace or attach ARC to an existing ML or research repo.

## The Research Loop

Each cycle moves through an approved objective, a scoped package, a visible run,
an evidence-backed result, a human decision, and project memory. A scoped package
is a bounded, approved unit of work.

<img src="asset/arc-workflow.png" alt="ARC logo" width="1000" />


| Stage | Command |
| --- | --- |
| Shape an idea | `/research-brainstorm` |
| Approve research intent | `/research-scope` |
| Create an executable unit | `/research-package` |
| Run and verify it | `/research-run` |
| Continue within an approved direction | `/research-auto` |

---

## Quick Start

Setup has two layers:

1. Install the skills so Claude Code or Codex can see the `/research-*` commands.
2. Attach the protocols and dashboard inside each research workspace you want to manage.

`/research-onboard` is an optional next step for workspaces that do not yet have
an approved Project objective.

### 1. Install the skills

Skills must be symlinked from this toolbox repo. Do not copy them: the helper
scripts resolve shared `lib/` code relative to this checkout.

> [!IMPORTANT]
> Run the install command from the Agentic Research Control Panel (ARC) repo, not from
> the research workspace you want to manage.

Set `DEST` to the appropriate location:

| Installation | Claude Code | Codex |
| --- | --- | --- |
| **Global** | `DEST="$HOME/.claude/skills"` | `DEST="$HOME/.codex/skills"` |
| **Project level** | `DEST="/path/to/your-research-workspace/.claude/skills"` | Keep skills in `$HOME/.codex/skills` and place project-specific rules in the workspace's `AGENTS.md`. |

Codex project-level behavior is handled by step 2, not by a separate
`<workspace>/.codex/skills` directory.

```bash
cd /path/to/Agentic-Research-Control-Panel
REPO="$(pwd)"
DEST="$HOME/.claude/skills"

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

**Expected:** the listed entries are symlinks that point back into this toolbox
repo. Use `DEST="$HOME/.codex/skills"` for the Codex global install, or the
project-local Claude Code path for a one-workspace Claude Code install.

Restart Claude Code or open a new Codex session, then type `/research-` to
confirm the commands are visible.

### 2. Attach the protocols to a research workspace

Run this inside the workspace you want the agent to work on. It can be empty or
already contain research code.

```bash
cd /path/to/your-research-workspace
PIPELINE=/path/to/Agentic-Research-Control-Panel

mkdir -p outputs/_scope outputs/_selfevolve
test -f AGENTS.md || cp "$PIPELINE/AGENTS.md" AGENTS.md
test -f CLAUDE.md  || cp "$PIPELINE/CLAUDE.md" CLAUDE.md
```

**Expected:** your research workspace now has the operating protocol files the
agent will read before doing research work.

> [!NOTE]
> If either file already exists, merge the ARC protocol
> into the existing project instructions instead of overwriting it.

Use `AGENTS.md` for Codex-facing project rules. Use `CLAUDE.md` for Claude Code
and for the shared research operating protocol.

### 3. Deploy and open the control panel

Ask the agent from inside your research workspace:

```text
/research-dashboard
```

**Expected:** `research_html/` appears in your workspace.

Start the local dashboard server:

```bash
python3.13 research_html/scripts/serve_dashboard.py ensure \
  --host 127.0.0.1 --port 8904 --max-port 8904 --json
```

Open the control panel:

[http://127.0.0.1:8904/research_html/index.html](http://127.0.0.1:8904/research_html/index.html)

Keep this tab open while the agent works. From this point on, the dashboard is
the shared interface for project scope, package status, live runs, evidence,
results, and human decisions.

> [!IMPORTANT]
> Serve the page through `research_html/scripts/serve_dashboard.py`, not a
> file-watching preview. Dashboard data files are refreshed in place by
> `research_html/assets/live-data.js`, so Scope projection and package status
> updates repaint without a full page reload.

Setup ends here. The workspace now has the skills, project protocols, and the
interface where you will monitor and ratify research work.

<details>
<summary><strong>Optional: keep dashboard facts synchronized after agent edits</strong></summary>

<br />

Optional turn-end automation can keep dashboard facts synchronized after agent
edits. Claude Code projects register the Stop hook in `.claude/settings.json`;
Codex projects use the equivalent `[[hooks.Stop]]` lifecycle hook.

The complete hook recipe lives in:

```text
skills/research-dashboard/references/stop-fact-propagation-hook.md
```

</details>

<details>
<summary><strong>Optional: onboard a workspace without an approved Project objective</strong></summary>

<br />

Run this only when the workspace has no approved Project objective and you want
the agent to help create one. Keep the control panel open before running this
command.

```text
/research-onboard
```

**Expected:** for an empty workspace, the agent scaffolds a small research
project and asks you for the objective. For an existing workspace, it reads the
project files, writes a compact prior-knowledge digest, and proposes a Project
objective. In both cases, it should ask you to accept, reject, or revise the
objective before it becomes active.

Example reply:

```text
Accept this proposal.
```

Onboarding stops at the Project proposal. It does not start a research campaign,
commit Scope by itself, or create research packages. Start `/research-auto`
later, when you are ready to run a gated campaign.

</details>

---

## How ARC Works

Setup gives the workspace a shared control surface. After that, the pipeline
turns research work into four states: idea, committed intent, executable package,
and verified run. Each state has one command that owns it.

### 1. Shape an idea

Use `/research-brainstorm` when the research idea is still rough.

```text
/research-brainstorm "Can a cheaper reranker improve validation recall?"
```

Brainstorming is intentionally cheap. It creates dashboard ideas and readable
idea pages, but it does not create packages or change the approved research
scope. When an idea is ready, the agent converts it into a Direction proposal.
You still decide whether that Direction becomes part of the project.

### 2. Commit the research intent

Use `/research-scope` when the goal, direction, task, or success gate needs to
be defined or changed.

```text
/research-scope "Define a Direction for validating the reranker idea against the current baseline"
```

Scope is the contract for the work. Project, Direction, and Task entries live in
the Scope log only after ratification. The agent can propose a change, but it
cannot silently move the research goal, rewrite the metric, or declare a new
task as approved. Pending proposals stay in Triage until you accept, reject, or
revise them.

Use `/research-onboard` before this step only when the workspace has no approved
Project objective yet. Onboarding proposes that first Project objective; it does
not start a campaign.

### 3. Create an executable package

Use `/research-package` after a Direction and its validation Tasks are already
accepted.

```text
/research-package from-scope <direction-id>
```

A package is the working unit the dashboard can track. It contains the plan,
task spine, status, evidence slots, result pages, and agent context for one
piece of research work. The package materializer reads committed Scope only. It
will not turn a pending idea or pending Triage item into executable work.

### 4. Run and verify the package

Use `/research-run` when the package exists and should advance.

```text
/research-run "Continue the active package"
```

The runner does not invent research direction. It executes the next legal step
inside an already scoped package: readiness checks, implementation or review,
launch, live monitoring, artifact propagation, result verification, and terminal
routing. If the dashboard, Project, Direction, Task, or package is missing,
`/research-run` stops and tells you which earlier command owns the missing
piece.

Results count only when they pass the package gate with evidence. Runtime
artifacts feed facts, facts feed package pages, and the final decision remains
visible in the control panel.

### 5. Let the loop continue

Use `/research-auto` when you want the agent to keep cycling within one approved
Direction until a measurable gate clears or a real stop condition appears.

```text
/research-auto "Improve validation recall" --gate "MRR@10 improves by 2 points"
```

`/research-auto` is the campaign conductor. It delegates formation to
`/research-brainstorm` and `/research-scope`, package creation to
`/research-package`, execution to `/research-run`, and learning capture to the
analysis and rule paths.

It does not add a shortcut around approval. Direction changes, scope changes,
terminal adoption, and unresolved blockers still surface as human decisions.

The opening screenshot shows the same loop in the interface: the dashboard gives
the project-level view, and the package lane shows the method candidate,
reference run, current status, gate, metric, and next route.

---

## A Complete Example Run

> [!NOTE]
> This section uses a placeholder dataset and metric. Replace them with a real
> demonstration when one is ready.

```text
In an existing research repo:

User:
  /research-dashboard

Expected:
  research_html/ exists and the dashboard opens locally.

User:
  /research-onboard

Agent:
  I found the repo goal, datasets, baseline, and likely validation metric.
  Here is the proposed project objective.

User:
  Accept this proposal.

Expected:
  The approved objective appears in the control panel.

User:
  /research-auto "Improve baseline retrieval on the validation split" \
    --gate "MRR@10 improves by 2 points"

Expected:
  A research package is created.
  A live run appears in the dashboard.
  The result page records the metric, evidence, and verdict.

User:
  Accept the result, revise the direction, or stop.

Expected:
  The decision is recorded, and the useful lesson is available to the next run.
```

---

## What ARC Preserves

After one loop, the repo should have more than logs and chat text. The useful
state is saved where the next agent and the human can read it.

| You see | What it means |
| --- | --- |
| **Approved goal** | The research question the agent is allowed to pursue. |
| **Research package** | One unit of work with plan, run state, result, and decision. |
| **Live run** | The experiment or command currently running, with status outside chat memory. |
| **Result package** | The answer to whether the work helped, tied to evidence. |
| **Decision record** | The human call: accept, revise, stop, archive, or continue. |
| **Lesson for next run** | What should be reused or avoided later. |

The internal names are Scope, Package, Live Run, Result, and Learning. This
README uses those names only after the user has seen the loop.

## Human Control Points

The pipeline keeps agent-assisted research tied to visible human decisions.

- You approve the research goal before work starts.
- You can watch active and recent runs in the control panel.
- You inspect the result package before deciding what counts.
- The agent records evidence instead of asking you to trust a chat summary.
- Useful lessons are carried into the next cycle deliberately.

Under the hood, Scope/Triage owns the approved research intent, result packages
tie claims back to evidence, and the Context Pack carries project memory forward.
Those details matter, but they should support the workflow rather than become
the first thing a new user has to learn.

## How ARC Fits Your Stack

AI research agents can propose and run work. Experiment trackers can record
metrics after a run. ARC sits between them: it keeps
the research goal, live state, evidence, decision, and next-cycle learning in
one place.

- Pair it with agent frameworks when you want their actions to land in a visible
  research workflow.
- Pair it with MLflow, Weights and Biases, DVC, or similar tools when those tools
  already track raw runs and metrics.
- Use it for experiment-driven research where code, data, and decisions all need
  to stay connected.
- Use it when you want agents to move faster while the research agenda stays
  visible and deliberate.

## Status

The dashboard, Scope/Triage system, package runner, live-run envelope,
fact-backed package surfaces, Context Pack, and Rule Store are implemented in
the toolbox. `/research-auto` composes them into a direction-level campaign
loop.

The current product boundary is the control panel and governance layer around
agent-assisted research work in a new or existing research workspace.

---

## Command Reference

### Daily commands

| Command | Use when | Output |
| --- | --- | --- |
| `/research-dashboard` | A workspace needs the shared control panel. | `research_html/` scaffold and validation. |
| `/research-onboard` | A workspace has no approved Project objective. | Empty-project scaffold or prior-knowledge digest, then a Project proposal. |
| `/research-brainstorm` | The research idea is still rough. | Brainstorm item and Direction proposal. |
| `/research-scope` | Project, Direction, Task, or scope revision needs approval. | Pending proposal and Scope transition after acceptance. |
| `/research-package from-scope <direction-id>` | An approved Direction or Task should become executable. | Package pages and dashboard entry. |
| `/research-run` | A scoped package should advance toward a terminal outcome. | Runtime artifacts, evidence propagation, verification, verdict routing. |
| `/research-auto` | One Direction should be pursued until a measurable gate clears or an honest stop fires. | Campaign ledger, package cycles, gate evaluation. |
| `/research-analysis` | A package needs human-curated rules or insights. | `analysis.html` updates through governed writes. |
| `/research-op` | Package, registry, rule, event, or Scope mutation must be applied safely. | Reject-before-write validation and audit log. |
| `/research-exp-live` | A long experiment needs structured launch, monitoring, resume, or harvest. | `status.json`, run index, live checks. |
| `/research-resource` | Compute servers or GPU allocations need typed tracking. | Resource registry and allocation ledger. |

### Main files and directories

```text
Agentic-Research-Control-Panel/
|-- README.md
|-- AGENTS.md
|-- CLAUDE.md
|-- workflow.ts
|-- skills/
|-- lib/
```

In a managed research workspace, the main generated surfaces are:

```text
research_html/                         # dashboard and package pages
research_html/live.html                # live runs page
research_html/packages/<pkg>/          # package pages
research_html/data/packages/<pkg>/     # fact-backed package tables
outputs/_scope/                        # approved and pending research intent
outputs/_live/                         # global run index
outputs/<pkg>/                         # package runtime records and artifacts
outputs/_selfevolve/                   # governed project memory
```

## Acknowledgements

The design was informed by prior work on auto-research agents, research skill
systems, and agent workflow methodology. This repo does not vendor those
projects. Its contribution is the governed control panel around agent-assisted
research: approved goals, visible runs, evidence-backed result packages, human
decisions, and reusable project memory.
