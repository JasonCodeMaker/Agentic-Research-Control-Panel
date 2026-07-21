# CLAUDE.md - Trustworthy Research Pipeline

This file is the agent operating contract for any project that adopts the
Trustworthy Research Pipeline. It is project-agnostic. A consuming project
copies this file into its repo root and prepends its project profile,
optimization objective, contribution spine, current best result, dataset
constraints, and budget gates. Keep the shared protocol below unchanged.

## What this pipeline produces

The pipeline produces an auditable research record in which:

- research intent is ratified before it becomes active;
- each executable Experiment has one specification and measurable gate;
- every Run binds its command to an immutable context snapshot;
- every claimed result resolves to protocol-aware evidence;
- every terminal route remains a visible human decision;
- useful wins, failures, and rules remain available to later queries.

`workflow.ts` is the executable package controller. The installed
`research-*` skills provide the task-specific entrypoints. Guarded commands,
not generated HTML or chat memory, mutate research state.

## One root and four storage roles

Resolve all managed data through `RESEARCH_ROOT`. Its default is
`<workspace>/.research`.

```text
.research/
|-- VERSION
|-- state/
|   |-- events.jsonl
|   |-- current.json
|   |-- migration.json                 # present after an explicit migration
|   `-- notes/
|-- audit/
|   `-- actions.jsonl
|-- experiments/
|   `-- <package>/<experiment>/<run>/
`-- interface/
```

The authority order is:

1. `.research/state/events.jsonl` for ratified intent and management history.
2. `.research/experiments/<package>/<experiment>/<run>/` for executed commands,
   measurements, and evidence.
3. `.research/audit/actions.jsonl` for command outcomes and rejections.
4. `.research/state/current.json` and `.research/interface/` as rebuildable
   projections.

Use state queries instead of parsing the event log directly. Use bounded Run
files instead of unbounded terminal scrollback.

### Human interface boundary

`.research/interface/` is a generated read model for people. Its existing
multi-page dashboard, package pages, modules, tables, navigation, and visual
layout remain intact. The interface is not an agent context store, a mutation
surface, or proof of a result.

Agents must not read interface HTML, JavaScript, or projected data to infer
Scope, package state, Experiment status, evidence, learnings, or the next
action. Query typed state and inspect the relevant Run directory. If the
interface disagrees with an authority, repair the typed source if needed and
rebuild the interface.

## Research object model

Scope is the versioned intent hierarchy:

```text
Project -> Direction -> Experiment
```

- `Project` owns the ratified objective and project constraints.
- `Direction` owns one approved research strategy.
- `Experiment` is the only executable specification. `Experiment.spec` owns
  purpose, configuration reference, gate, and control mode.
- `Package` groups working state and Experiments for a bounded research unit. It
  is not a Scope level.
- `Run` is one execution attempt for one Experiment.

There is no independent Task object. Any former Task is represented by
`Experiment.spec`; do not recreate Task as a parallel plan, milestone, page, or
runtime entity.

## The five protocols the agent obeys

The protocols form a stack. Keep this file as the always-loaded index. Load the
owning skill, command help, or reference only when the current task reaches that
surface.

### 1. Research Workflow

`workflow.ts` defines legal package states, Run tickets, open-Run stop gates,
adaptive monitoring, and multi-Experiment routing:

```bash
node <pipeline-root>/workflow.ts next --json '<snapshot>'
node <pipeline-root>/workflow.ts schema
```

Follow the returned ticket. Apply `requiredMutations` through `research-op`,
emit each `perRun[].statusLine`, and end the turn only when `stopGate.ok` is true
or the ticket identifies the smallest blocking human decision.

### 2. Research State and Experiment Contract

Create or materially restructure packages through `research-package`, never
through ad hoc directories. Materialization reads only ratified Scope. Pending
Triage proposals do not authorize execution.

All package and Experiment mutations go through `research-op`. Do not hand-edit
the EventStore, its current projection, audit records, or generated interface.
Run launch goes through `research-run` and `lib.experiments`, which place
canonical Run artifacts under:

```text
.research/experiments/<package>/<experiment>/<run>/
```

A Run directory may contain specialized checkpoints or artifacts, but its
canonical envelope is `run.json`, `context.json`, `status.json`,
`events.jsonl`, `metrics.jsonl`, `log.txt`, and `result.json`.

### 3. Fact Propagation Contract

Every observed artifact is evidence, not automatically a scientific verdict.
Checkpoints, candidate records, sentinels, phase markers, terminal markers, and
comparable files must be registered through the owning operation in the same
turn they are observed.

A user instruction that changes a constraint, plan, metric, baseline, roster,
or scope is also a locked fact. Write it to its typed owner and propagate the
affected status in the same turn. Use `research-op` for event reconciliation,
explicit fanout, rule changes, status repair, and audited mutations.

### 4. Learning and Rule Protocol

Verified results may create typed `learning` records. Generalizable,
evidence-backed guidance may be promoted into governed `rule` records. Failed
methods remain retrievable so later work does not repeat them blindly.

Upstream Run evidence remains the witness. A learning or rule is an indexed
claim that must resolve back to that witness. In-progress facts may update after
their evidence exists. Terminal adoption, supersession, archival, reopening,
and Scope impact require the relevant human ratification.

Do not read a generated learnings page before proposing work. Request bounded
package context or query the relevant learning and rule aggregates.

### 5. Refinement Guardrails

Treat the consuming project's contribution spine as a compatibility constraint
unless the user explicitly asks to replace it. Every refinement must explain
how it sharpens the current research claim under the approved metric, protocol,
and budget.

## Context and Run binding

Before package work, request bounded context:

```bash
python <research-op-script> context <package-id> --workspace <workspace>
```

The response is ephemeral. Do not persist it as a package-level context file,
copy it into the interface, or treat it as authority after state changes.

At Run authorization, the launcher performs a fresh state query and freezes the
selected content into:

```text
.research/experiments/<package>/<experiment>/<run>/context.json
```

That file is immutable and bound by hash from `run.json`. It answers which
ratified intent, rules, learnings, and Experiment spec governed that exact Run.
Later management changes apply to later Runs; they do not rewrite history.

## Scope and Triage

Project, Direction, Experiment, and scope revisions enter Triage before
commitment. The agent may draft a proposal and explain its effect. It may not
accept its own proposal.

A committed Scope transition requires explicit human ratification and the gated
writer documented by `research-scope` and `research-op`. Terminal transitions
that change adoption or archive state also require the T1 acknowledgement.

If execution discovers that the approved Experiment is insufficient, stop and
propose a revision. Do not smuggle new intent into a command, config file, Run
note, package page, or generated interface.

## Cross-cutting agent rules

- **Build context first.** Read the invocation and project profile, then query
  the smallest relevant Project, Direction, Package, Experiment, learning, and
  rule slice. Inspect only the Run evidence required by the task.
- **Runtime truth wins.** Validate the live process, structured Run status,
  logs, metrics, and files before changing management state. Recalled content is
  unverified.
- **Use guarded writes.** Research-affecting mutations go through the owning
  skill or `research-op`. Direct edits to managed state and generated interface
  files are violations.
- **Use live Run artifacts.** Long experiments use `research-exp-live` when
  available. Structured status is the routine source; bounded logs are a debug
  fallback.
- **Use the resource registry.** Compute facts and placements come from
  `resource` and `resource_allocation` state through `research-resource`, not
  recalled prose.
- **Keep long work observable.** Launch long training, preprocessing, download,
  sync, and remote jobs in named `tmux` sessions unless the user requests
  another supported runner.
- **Preserve ETA honesty.** Keep ETA unknown until observed throughput supports
  it, then update it from measurements.
- **Make surgical changes.** Touch only the owning source and run its contract
  checks. Do not refactor adjacent code without authorization.
- **Do not rerun the anchor by default.** Trust verified checkpoint evidence and
  the project protocol unless the user asks to revalidate it.

## Interface rebuild

The human interface is rebuilt atomically from current state and Run evidence:

```bash
cd <pipeline-root>
python -m lib.interface.serve --workspace <workspace> ensure --json
```

This command requires an already versioned managed root. If setup or migration
is required, stop and use `research-init`. Starting or rebuilding the interface
never authorizes a Scope change or Run.

## Per-project customization

A consuming project prepends sections for:

- **Project:** system, datasets, agent stack, and one-paragraph purpose.
- **Motivation and Goal:** the central bottleneck.
- **Global Optimization Objective:** the primary metric and success rule.
- **Project-specific rules:** dataset, compute, budget, and evaluation
  constraints.
- **Contribution Spine:** the non-negotiable components of the research story.
- **Current Best:** checkpoint, metric values, protocol, and validation seeds.

Project-specific content is user-owned. The five shared protocols remain
unchanged.
