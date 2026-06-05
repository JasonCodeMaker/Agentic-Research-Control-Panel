# /research-auto front-door intake — folding Step 3 capabilities into auto without moving authority

**Date:** 2026-06-05 · **Status:** IMPLEMENTED 2026-06-05 (TDD; `skills/research-auto/scripts/admission.py` + `tests/research-auto/test_admission.py`). Admission coverage now includes the A-G state machine plus default-autonomy behavior: new Task proposals default to `autonomous`, surface all four dial choices, allow explicit override, and reject invalid or internally inconsistent levels. Built as Stage 0.5 of `plan/2026-06-05-research-auto-maturation-wiring.md`; SKILL.md §"Stage 0.5" is the operating contract. Not committed.

## Decision

`/research-auto` should become the user's post-init front door. If the project is not yet ready to run, it should drive the missing Step-3 formation work by invoking the same R1-R3 capabilities (`research-scope`, `research-lit`, `research-ideate`, `research-brainstorm`) and then stop at the existing human gates.

The boundary is strict:

```text
/research-auto may discover that Step 3 is missing.
/research-auto may run the Step-3 formation roles.
/research-auto may propose Project / Direction / Task nodes through Triage.
/research-auto may materialize a package only from committed Scope SSOT state.
/research-auto must never ratify or dispose Triage on behalf of the user.
```

So the simplified user story can be:

```text
Init dashboard -> /research-auto -> review/accept proposals when prompted
```

But the trust story remains:

```text
formation capability belongs inside auto;
commit authority remains with the user / Triage.
```

## Why R1-R3 and Step 3 overlap

The overlap is real and should be embraced rather than hidden.

**Step 3 is a user-journey transaction.** It asks whether a vague idea can become an official research direction:

```text
idea -> Direction proposal -> user ratify -> SSOT transition -> package materialization
```

Its core output is not "some ideation happened"; its core output is a committed Direction/Task and a package that the loop may legally run.

**R1-R3 are reusable role capabilities.** They can be used in two modes:

| Role | Formation mode (Step 3) | Loop mode (after package exists) |
| --- | --- | --- |
| R1 scope | propose Project / Direction / Task nodes; never commit them | read the accepted node and propose scoped revisions when evidence demands |
| R2 search/read | ground vague ideas before a Direction proposal | fetch and synthesize sources for an active direction |
| R3 ideate | generate and rank candidate directions/tasks | propose next hypotheses, ablations, or repairs under the accepted direction |

The mistake would be treating Step 3 and R1-R3 as separate implementations. They should share the same role machinery, with different authority rules.

## Front-door admission state machine

`/research-auto` starts with an admission check before any experiment loop.

### A. Dashboard missing

Condition:

```text
research_html/index.html missing
```

Action:

```text
Stop and instruct the user to run /research-dashboard.
```

Rationale: dashboard scaffolding is an init operation, not an auto-loop mutation.

### B. No committed Project node

Condition:

```text
outputs/_scope/transitions.jsonl has no active level=project node
```

Action:

```text
Run the onboard/scope proposer path.
Create a Project proposal in Triage.
Stop with "user must ratify Project".
```

Forbidden:

```text
No scope-transition commit.
No Direction creation.
No package materialization.
```

### C. Project exists, no active Direction

Condition:

```text
active Project exists;
no active level=direction child exists
```

Action:

```text
Run R2/R3 formation mode:
  - use research-lit for factual grounding when needed
  - use research-ideate / research-brainstorm for candidate directions
  - use lib/ranking when several candidates must be ordered
Build one Direction proposal with yardstick:
  hypothesis / metric / baselines / success_predicate
Write it to Triage.
Stop with "user must accept/reject Direction".
```

Forbidden:

```text
No direct SSOT write.
No package creation from pending proposal.
```

### D. Direction exists, no committed Task/milestone

Condition:

```text
active Direction exists;
no active level=task child / validation milestone exists
```

Action:

```text
Run milestone planning.
Propose Task nodes through Triage with default autonomy_level=autonomous.
Surface autonomy choices:
  supervised / checkpoints / async / autonomous
Stop with "user must accept/reject Task plan".
```

Forbidden:

```text
No experiment launch.
No package materialization from pending Task proposals.
```

### E. Direction + Task exist, package missing

Condition:

```text
committed Direction and Task nodes exist;
no package carries sourceScopeNode/sourceScopeMilestones for them
```

Action:

```text
Run create_from_scope against committed transitions only.
Create the package pages and inventory entry.
Continue to readiness preflight.
```

This is a mechanical materialization step, not a scope decision.

### F. Package exists, readiness incomplete

Condition:

```text
package exists but readiness lint fails for the selected autonomy horizon
```

Action:

```text
Surface missing plan / impl / docs / result rows / todo / ledger items.
Default readiness dial is autonomous unless the user/context chose another level.
At supervised: allow a human-visible repair path.
At async/autonomous: stop before entering the unattended loop if readiness is incomplete.
```

### G. Package ready

Condition:

```text
committed Project + Direction + Task + materialized package + readiness pass
```

Action:

```text
Enter the production R1-R7 loop.
```

## Implementation placement

Insert this as **Stage 0.5** in `plan/2026-06-05-research-auto-maturation-wiring.md`, after Stage 0's production-loop contract and before Stage 1's real code role.

Stage 0.5 should add a small admission layer, not a second orchestrator:

```text
research-auto front door
  -> inspect admission state
  -> either run formation/proposal mode
  -> or enter production run_tick
```

Suggested deterministic helpers:

```text
detect_admission_state(root) -> state
build_admission_actions(state, context) -> actions
validate_admission_action(action) -> reject | None
```

Suggested action types:

```text
handoff_dashboard_init
propose_project
propose_direction
propose_task
materialize_package
run_readiness
enter_auto_loop
block_for_user_disposal
```

All actions that write intent still route through the existing Triage / research-op surfaces.

## Tests

Stage 0.5 is not done until these are green:

1. **No Project blocks at ratification.**
   Given no active Project node, `/research-auto` emits a Project proposal action and never writes `outputs/_scope/transitions.jsonl`.

2. **No Direction proposes, never commits.**
   Given an active Project but no Direction, `/research-auto` runs formation mode and writes/returns a pending Direction proposal, but no package is created.

3. **Pending Triage does not duplicate proposals.**
   Given an equivalent pending Direction proposal, `/research-auto` reports the pending item and waits for user disposal instead of proposing another one.

4. **Package materialization reads committed Scope only.**
   Given accepted Direction + Task transitions, `/research-auto` may call `create_from_scope`; given only pending proposals, it must reject materialization.

5. **Ready package enters the loop.**
   Given Project + Direction + Task + package + readiness pass, `/research-auto` calls the Stage-0 production driver instead of formation mode.

6. **Authority cannot be smuggled through role returns.**
   A role return that includes `decision=accept`, `scope-transition`, or direct package writes is rejected before any mutation.

7. **Task autonomy defaults to Autonomous but remains user-visible.**
   Given an active Direction but no Task, `/research-auto` emits `propose_task` with `autonomy_level="autonomous"` and `autonomy_choices=["supervised","checkpoints","async","autonomous"]`; context may override the level before the proposal is accepted, and invalid levels are rejected.

## README impact

Once implemented, the user-facing README can be simplified without weakening trust:

```text
1. /research-dashboard
2. /research-auto
3. Accept/reject proposals when /research-auto reaches a ratification gate
```

The old Step 3 remains conceptually valid, but it becomes an internal admission branch of `/research-auto` rather than a separate command the user must remember. The docs should still expose `/research-brainstorm`, `/research-scope`, and `/research-package` as manual escape hatches for users who want to drive formation explicitly.

## Non-goals

- Do not let `/research-auto` ratify Project, Direction, or Task nodes.
- Do not let `/research-auto` materialize packages from pending Triage proposals.
- Do not hide Triage from the dashboard.
- Do not merge the Step-3 formation code with the Step-4 run code in a way that weakens the state checks.
- Do not remove `/research-brainstorm`, `/research-scope`, or `/research-package`; they remain explicit manual commands and reusable role skills.

## One-line product contract

After init, `/research-auto` is the single command the user can try first; if the project is not ready to run, it becomes a guided proposal-and-ratification front door, not an unauthorized auto-committer.
