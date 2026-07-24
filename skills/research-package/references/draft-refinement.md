# Draft refinement pipeline

## Boundary

This workflow begins after `DRAFT_MATERIALIZE` and ends when the user accepts
the complete Draft. The Package remains `DRAFT / REFINING` throughout. Draft
refinement does not commit Scope, create executable Direction or Experiment
aggregates, edit research code, or launch a Run.

The two phases are:

```text
Phase 1: Overview + Plan
  -> user review
  -> accepted Overview/Plan baseline
  -> Phase 2: Implementation + Results + derived Tracker + conditional Docs
  -> user review
  -> Draft refinement complete
```

The user may request another document at any point. That request is a
cross-cutting authoring action, not a third mandatory phase.

## Shared phase harness

Run this sequence before each phase:

1. Load the full governed Draft context, the owning page contracts, and the
   smallest repository facts needed for the phase.
2. Resolve facts from the workspace. Do not ask the user for a path, schema,
   configuration, dependency, or existing implementation that can be
   inspected.
3. Build one complete candidate model internally. Use it to find the few
   decisions whose answers affect the most downstream fields.
4. Invoke the installed `grilling` skill. Ask one question at a time and give
   a recommended answer. Ask at least one question and no more than five.
5. Write the complete phase through guarded Draft operations. Put each fact in
   its typed owner and do not create a second checklist or context pack.
6. Validate required authored fields, legal derived states, cross-page
   consistency, references, and links.
7. Build the human projection for review. The agent still uses governed state,
   not generated HTML, as its context.
8. Show the complete phase once. Keep hashes and receipts internal. Revise
   until the user explicitly accepts it.

Direct wording or formatting requests do not restart grilling. Invoke a
targeted grilling pass only when a revision introduces a new motivation,
research-design, or execution-strategy decision.

If `grilling` is unavailable, stop and report the missing dependency. Do not
silently replace the required interview.

## Phase 1: complete Overview and Plan

Phase 1 turns the brief Research Intent and high-level Experiment needs from
the Brainstorm into complete Overview and Plan content.

### Overview

Complete every module required by the current Overview contract. The agent
authors:

- Package identity, title, and name;
- `abstract`;
- `problem`, `motivation`, `hypothesis`, and `objective`.

Derive the Experiment queue from Plan and resolve source and artifact anchors
from their canonical paths.

Problem states the research gap. Motivation explains why it matters and the
high-level solution rationale. Objective states the verifiable target.
Hypothesis gives the falsifiable expected relationship. Keep the four roles
distinct.

### Plan

Create the complete ordered Experiment timeline. Every Experiment must define
all authored fields required by the current Plan contract:

- stable id and human label;
- planned order and explicit `after` dependencies;
- purpose;
- canonical `config_ref`;
- measurable gate;
- `control_mode`;
- evidence output destination;
- whether it measures a result;
- whether it requires code; and
- the initial complexity assessment required by the renderer.

Do not move code locations, implementation steps, verification commands, or
Result-table rows into Phase 1.

### Authored and derived fields

Completeness does not mean inventing runtime evidence. The agent writes
authoring fields. The system derives the initial legal state:

```text
status = PLANNED
evidence = absent
locked = false
next eligible = derived from order and dependencies
task and document links = derived from declared fields
artifact roots = derived from canonical paths
```

Do not use `unmeasured` as a substitute for a missing Phase 1 field. Do not
invent a result, evidence reference, lock, active Run, or insight.

### Phase 1 validation

Before review, verify that:

- every required Overview and Plan module renders with legal content;
- all four Research Intent fields are non-empty and semantically distinct;
- Experiment ids are unique and the queue matches the timeline one to one;
- planned order is complete;
- every dependency exists and the dependency graph is acyclic;
- gates are measurable and control modes use the allowed enum;
- config, output, task, and document references are valid; and
- no required authored field falls back to `unmeasured`.

### Phase 1 review and soft lock

Show Overview and Plan together. User acceptance soft-locks exactly the
accepted Research Intent and Experiment timeline. Phase 2 may elaborate that
baseline but may not silently change it.

Bind the accepted field set to a content digest through an owning guarded
Draft checkpoint when one exists. A Phase 2 edit must not invalidate the
baseline merely because it advances the overall `draftRevision`.

If the installed runtime has no guarded Draft checkpoint, keep the acceptance
procedural and report that durable enforcement is unavailable. Do not invent a
state field, duplicate the accepted pages in a document, or claim a persisted
lock.

Any change to Research Intent, the Experiment roster, purpose, protocol, gate,
dependency, or evidence destination returns to Phase 1 and requires another
complete review.

## Phase 2: complete execution design

Phase 2 reads the accepted Phase 1 baseline and inspects the exact repository,
configuration, data, environment, and verification surfaces before asking its
grilling questions.

### Implementation

Give every Experiment an explicit implementation disposition. When work is
required, define one or more ordered Changes. Each Change contains:

- title and order;
- validating Experiment ids;
- `plan.how_it_changes`;
- code locations with stable ids, roots, relative paths, actions, predicates,
  and pre-edit baselines; and
- verifications with stable ids, labels, dependencies, and runnable argument
  list commands when automation is possible.

A no-change Experiment must still state which existing implementation it
reuses and how the agent will verify that reuse. Do not add pseudo-code,
Hypothesis copies, Plan coverage maps, test catalogs, or editable checkbox
state.

### Results

For every Experiment, make one explicit decision:

- no human Result table helps the decision; or
- one or more complete `resultSchema` tables are required.

Absence without that decision means Phase 2 is incomplete. A non-empty schema
fixes table type, rows, selectors, metrics, units, and nullability. It contains
no measured value, verdict, prose conclusion, or evidence path.

### Tracker

Do not author Tracker rows. Derive Tracker from the accepted Experiment order,
Implementation Changes, Result-schema decisions, planned artifact locations,
and later Run evidence. Each Experiment has its Change tasks followed by one
Run task.

During Draft refinement, tasks are planned. Do not present one as an active
Run or completed implementation. Checkbox state, totals, current or next task,
and artifact locations remain projections of their owners.

### Guide Doc context-sufficiency check

After Implementation and Results are complete, ask:

> Can an execution agent with no chat history complete this work safely,
> deterministically, and verifiably from the reviewed typed content?

Create a Guide Doc when any of these apply:

- commands have multiple stages or a strict order;
- the work needs a special environment, remote machine, HPC node, tmux
  session, or long-running process;
- data preparation, path mapping, or an external dependency is not obvious;
- execution has branches, recovery procedures, or stop conditions;
- several Experiments share one complex protocol; or
- typed fields explain what changes but not how to operate safely.

Prefer one document per shared workflow, not one per Experiment. A Guide Doc
references Experiment and Change ids and may explain setup, sequencing,
recovery, and diagnosis. It must not replace or copy Plan, Implementation, or
Results authority.

Record one decision for every assessed workflow:

```text
NOT_REQUIRED + reason
REQUIRED + governed document references
```

The user may require a document even when the check returns `NOT_REQUIRED`.

### Phase 2 validation and review

Before review, verify that:

- the accepted Phase 1 content has not drifted;
- every Experiment has complete Implementation coverage;
- code locations and actions are valid;
- every Change has at least one meaningful verification;
- every Experiment has an explicit Result-table decision;
- Result schemas have unique selectors and exact metrics and units;
- Tracker matches Plan, Implementation, Results, and artifact destinations;
- every workflow has a Guide Doc decision; and
- every required document exists and its references resolve.

Show Implementation, Results, Tracker, the Docs index, required Guide Docs,
and a concise statement that the Phase 1 baseline is unchanged. Review the
Package as one unit so shared code locations, dependencies, and documents stay
consistent.

User acceptance completes Draft refinement. The Package still remains
`DRAFT / REFINING`.

## Rollback rules

- A Phase 2 edit to a Phase 1-owned field invalidates both reviews and returns
  to Phase 1.
- A Phase 2-only edit invalidates only the Phase 2 review.
- A requested document that changes an owning field returns to that field's
  phase. A purely explanatory document receives its own review.
- A discovered research-question change returns to `research-brainstorm`.

## Runtime support boundary

This reference defines the authoring strategy. It does not loosen current
management policy.

Never work around missing Draft support by creating executable aggregates,
calling active-only Result or Change mutations, editing SQLite or compatibility
exports, hand-editing generated HTML, or storing another context pack.

If the installed guarded writer or renderer cannot persist or display a
required Draft field, preserve all supported work, report the exact capability
gap, and stop before claiming that the phase is complete.

## Done condition

Draft refinement is complete only when:

- the user accepted complete Overview and Plan content;
- the accepted Phase 1 content has not drifted;
- the user accepted complete Implementation, Results, derived Tracker, and
  required Docs;
- every required authored field and derived state passes validation;
- no phase relies on `unmeasured`, duplicated truth, or fabricated runtime
  evidence; and
- the Package remains `DRAFT / REFINING` with no code or Run execution.
