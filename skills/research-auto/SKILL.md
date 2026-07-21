---
name: research-auto
description: "Use when the user invokes /research-auto or asks to run an autonomous research campaign over one committed Direction toward a measurable gate."
allowed-tools: Bash(python3 *), Read, Grep, Glob, Agent
---

# research-auto

## Purpose

`/research-auto` runs a campaign over one Direction. `/research-run` advances one materialized
package; `/research-auto` decides what happens after each terminal experiment:

```text
Direction + measurable gate
  -> resolve or ratify the charter
  -> materialize a package
  -> run one experiment
  -> verify its result
  -> record the Campaign cycle
  -> stop, or design the next experiment
```

The loop ends when verified evidence clears the Direction's gate, the cycle budget is exhausted, no
legal candidate remains, or the campaign reaches a decision reserved for the user.

`scripts/conductor.py` owns deterministic routing, gate evaluation, Campaign cycle records, away-mode
handoff bundles, and the authority guard. It does not own Project, Direction, Experiment, Package,
Run, Learning, Rule, or Decision mutations.

## Authority

The campaign adds no independent writer. The conductor submits `CampaignUpdated` through the
`research-op` management gateway. Every other mutation stays with its owning use case;
materialization also uses that gateway, while the experiment harness writes only its own Run
directory.

| Decision | Owner | Route |
| --- | --- | --- |
| Project or Direction acceptance | human | Triage proposal, then user disposition |
| Gate, dial, and max cycles | human | Ratified as the campaign charter |
| New validation Experiment spec | dial-dependent | Triage pause for `SUPERVISED` and `CHECKPOINTED`; `AGENT_DEFERRED_ACK` Experiment commit plus queued acknowledgement for `DEFERRED` and `AUTONOMOUS` |
| Bind an accepted Experiment to a Package | agent within ratified scope | `research-op --target experiments-row` |
| Run launch, monitoring, and terminal result | `/research-run` | Experiment and Run contracts |
| Insight or package Rule | explicit editorial decision | `/research-analysis` |
| Package terminal transition or adoption | human acknowledgement | `/research-run` |
| Campaign cycle or handoff bundle | conductor | `research-op` campaign gateway |

The conductor never disposes Triage, commits Project or Direction scope, edits an interface file, or
moves the gate after a failure.

## Storage model

The workspace has one managed root:

```text
.research/
├── state/          # authoritative events and current fold
├── audit/          # command/action audit
├── experiments/    # immutable run evidence
└── interface/      # derived human view
```

Campaign cycles and handoff bundles are fields of the `Campaign` aggregate whose id equals the
Direction id. There is no separate campaign ledger file and no separate PACK file. The Context Pack
is an ephemeral query over state; a Run freezes the exact launch context in its own
`.research/experiments/<pkg>/<experiment>/<run>/context.json`.

Do not edit files below `.research/state/` or `.research/interface/`. Use bounded queries for reads
and typed commands for writes.

## Resources

`<pipeline-root>` is the Trustworthy Research Pipeline checkout.

| Asset | Path |
| --- | --- |
| Campaign conductor | `skills/research-auto/scripts/conductor.py` |
| Admission logic | `skills/research-run/scripts/admission.py` |
| Scope and Triage workflow | `/research-scope` |
| Direction-to-package materializer | `skills/research-package/scripts/create_from_scope.py` |
| Mutation and query gateway | `skills/research-op/scripts/research_op.py` |
| Experiment evidence | `.research/experiments/<pkg>/<experiment>/<run>/` |
| Human interface | `.research/interface/` |

Conductor commands:

```bash
python3 skills/research-auto/scripts/conductor.py status \
  --workspace . \
  --direction-id <direction-id> \
  --max-cycles <N> \
  --dial <DIAL> \
  [--gate "<gate>"] \
  [--no-candidate]

python3 skills/research-auto/scripts/conductor.py gate-eval \
  --measured <value> \
  --gate "<gate>"

python3 skills/research-auto/scripts/conductor.py append-cycle \
  --workspace . \
  --direction-id <direction-id> \
  --record '<cycle-json>'

python3 skills/research-auto/scripts/conductor.py pack \
  --workspace . \
  --direction-id <direction-id> \
  --bundle '<handoff-json>'
```

Use `--research-root <path>` only when the workspace intentionally overrides the default
`.research` root.

## Charter

An invocation has four inputs:

- `direction`: a committed Direction id such as `dir/retrieval-v2`, or free text that must be shaped;
- `gate`: one numeric comparator clause such as `R@1 >= 48`;
- `dial`: one of `SUPERVISED`, `CHECKPOINTED`, `DEFERRED`, or `AUTONOMOUS`;
- `max-cycles`: a positive campaign budget, default 5.

For a committed Direction, its `spec.success_gate` is authoritative. If the invocation supplies a
different gate, submit a Direction revision through Triage and pause. Do not override the committed
gate in Campaign state.

## Procedure

### 0. Read admission state

Use the state-backed `/research-run` admission logic. The generated interface is not an execution
prerequisite.

```python
import sys
sys.path.insert(0, "<pipeline-root>/skills/research-run/scripts")
import admission

context = admission.build_research_context(".")
state = admission.detect_admission_state(".")
actions = admission.build_admission_actions(
    state,
    {
        "pending": context["pending_proposals"],
        "direction_id": (context["direction"] or {}).get("id"),
    },
    root=".",
)
```

Route missing prerequisites as follows:

- `NO_PROJECT`: hand off to `/research-onboard` and pause.
- `NO_DIRECTION`: shape and ratify the campaign Direction in step 1.
- `NO_EXPERIMENT` or `NO_PACKAGE`: continue to campaign design and materialization.
- `NOT_READY` or `READY`: continue through the normal `/research-run` path.

Surface any returned `next_step` object without paraphrasing its authority boundary.

### 1. Resolve the charter

Run:

```bash
python3 skills/research-auto/scripts/conductor.py status \
  --workspace . \
  --direction-id <direction-id> \
  --max-cycles <N> \
  --dial <DIAL> \
  --gate "<gate>"
```

Handle `action.type`:

- `FORM_DIRECTION`: invoke `/research-brainstorm`, then submit the Direction, gate, dial, and cycle
  budget through Triage. Use the single semantic review from `research-scope`
  and pause for ratification.
- `AWAIT_RATIFICATION`: if the semantic review has not been shown, show it
  once through `research-scope`; otherwise report that the user decision is
  still pending without repeating the proposal or exposing its id and hash.
- `ASK_USER`: ask for a gate with one comparator clause.
- any other route: the committed charter is usable.

### 2. Materialize package scope

For `MATERIALIZE_PACKAGE`, first make sure the Direction has accepted Scope Experiments.

- At `SUPERVISED` or `CHECKPOINTED`, use `/research-scope` to propose missing Experiments and pause for
  Triage.
- At `DEFERRED` or `AUTONOMOUS`, shape a formal `level=experiment` node containing only
  `purpose`, `config_ref`, `gate`, and `control_mode`; validate the intended action with
  `conductor.validate_campaign_action(...)`, and commit it through
  `research-op --op scope-transition` with `gate=AGENT_DEFERRED_ACK` and a non-empty
  `deferred_ack`.

Then check materialization:

```bash
python3 skills/research-package/scripts/create_from_scope.py \
  --workspace . \
  --direction-id <direction-id> \
  --check \
  --json
```

If `materializable` is true:

```bash
python3 skills/research-package/scripts/create_from_scope.py \
  --workspace . \
  --direction-id <direction-id>
```

For a later campaign package under the same Direction, provide a fresh
`--id <YYYY-MM-DD>-<slug>-c<N>`. Never reopen a terminal package by editing its projection.

### 3. Execute one route at a time

Re-run `status` after every accepted action.

- `RUN_PACKAGE`: delegate the open package to `/research-run`. That skill owns readiness, resource
  allocation, launch, monitoring, result verification, and terminal routing.
- `DESIGN_EXPERIMENT`: follow the design procedure below.
- `SUCCESS_EXIT`, `HALT_BUDGET`, `HALT_NO_CANDIDATE`, or `ASK_USER`: go to step 5.

Do not reproduce `/research-run` logic inside the conductor.

### 4. Design and harvest a cycle

For `DESIGN_EXPERIMENT`, query the current Context Pack through the gateway:

```bash
python3 skills/research-op/scripts/research_op.py \
  context <package-id> \
  --workspace .
```

The query is ephemeral. Use its Project, Direction, package controls, Experiment specs, pending
Decisions, applicable Rules and Learnings, failed methods, and evidence references. Pending proposals
are collision warnings, not accepted Scope.

Draft the next hypothesis from that context and verified run evidence. If several candidates remain
plausible, rank them independently. First ratify the new Experiment through Scope. Then bind that
same accepted aggregate to the Package:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace . \
  --pkg <package-id> \
  --op insert \
  --target experiments-row \
  --payload '{
    "scope_experiment_id":"experiment/<direction>/reranker-variant",
    "local_id":"P3",
    "status":"READY",
    "output":".research/experiments/<package-id>/P3/<run-id>/result.json"
  }'
```

`experiments-row` binds execution metadata only. It rejects `purpose`, `config_ref`, `gate`,
`control_mode`, or a copied `spec`. Do not attach an Experiment to invented or pending scope.

When `/research-run` reaches a terminal Run:

1. read the verdict and measured value from the finalized result;
2. evaluate the campaign gate with `conductor.py gate-eval`;
3. record useful mechanism-level learning through `/research-analysis`;
4. append the witnessed Campaign cycle.

The cycle command requires an existing Package, Experiment, and terminal Run:

```bash
python3 skills/research-auto/scripts/conductor.py append-cycle \
  --workspace . \
  --direction-id <direction-id> \
  --record '{
    "cycle":3,
    "direction_id":"<direction-id>",
    "pkg_id":"<package-id>",
    "exp_id":"P3",
    "run_id":"<run-id>",
    "hypothesis":"The reranker improves recall under fixed controls.",
    "verdict":"FAIL",
    "measured":"46.1",
    "gate_eval":"FAIL",
    "evidence":".research/experiments/<pkg>/P3/<run-id>/result.json",
    "next_action":"DESIGN_EXPERIMENT"
  }'
```

`append-cycle` rejects incomplete records, illegal verdicts, a non-terminal Run, mismatched ownership,
duplicate cycle numbers, and `gate_eval=PASS` without `verdict=PASS`.

For `DEFERRED` and `AUTONOMOUS`, append an away-mode handoff bundle after the cycle:

```bash
python3 skills/research-auto/scripts/conductor.py pack \
  --workspace . \
  --direction-id <direction-id> \
  --bundle '{
    "attempted":"cycle 3: P3 reranker",
    "found":"FAIL, 46.1 against R@1 >= 48",
    "hypothesis_state":"unsupported",
    "next_action":"DESIGN_EXPERIMENT",
    "blocking_decision":"none"
  }'
```

This bundle is part of the Campaign aggregate. It is not a second context store.

### 5. Exit

Build the report from Campaign cycles and referenced run evidence.

- `SUCCESS_EXIT`: require a recorded `gate_eval=PASS`, `verdict=PASS`, and resolvable evidence. Let
  `/research-run` handle the package transition and T1 acknowledgement. Adoption remains a human
  decision.
- `HALT_BUDGET`: report the exhausted budget, propose extend, revise, or archive through Triage, then
  pause.
- `HALT_NO_CANDIDATE`: report why no legal Experiment remains, propose a scope revision or archive,
  then pause.
- `ASK_USER`: ask the single blocking question.

Every exit report includes cycles used, each hypothesis and verdict, measured value against the gate,
evidence path, queued acknowledgements, and the route's `next_step`.

## Directive changes

A user instruction that changes constraints, metrics, baselines, or experiment design is a
`DIRECTIVE_CHANGE`. Route it to its typed owner in the same turn and re-run `status`.

- Package or Experiment changes go through `research-op`.
- Direction changes become Triage proposals and pause.
- A `dial_revert` returns affected Experiment specs to `SUPERVISED` until they are grounded again.

The campaign never rewrites its own charter.

## Output contract

| Output | Authoritative home | Writer |
| --- | --- | --- |
| Campaign cycles and handoff bundles | `Campaign` aggregate in `.research/state/` | conductor through `research-op` |
| Project, Direction, Experiment, Package, Decision, Learning, Rule | unified research state | owning use case through `research-op` |
| Run context, logs, metrics, and result | `.research/experiments/<pkg>/<experiment>/<run>/` | experiment runtime |
| Command audit | `.research/audit/actions.jsonl` | management gateway |
| Human pages | `.research/interface/` | `lib.interface` atomic rebuild |

## Done condition

The campaign is complete only when one of these conditions holds:

1. a witnessed Campaign cycle records `gate_eval=PASS`, and `/research-run` has completed terminal
   routing with its acknowledgement collected or queued;
2. a halt route has produced its report and Triage proposal;
3. `ASK_USER` has surfaced the blocking question.

An open Run is not a stopping condition. Continue monitoring through `/research-run`.

## Error path

| Symptom | Action |
| --- | --- |
| `GateUnparseable` | Ask for one numeric comparator clause |
| `validate_campaign_action` rejects | Drop the action and use the Triage pause route |
| `append-cycle` rejects | Repair the record from authoritative Run state; do not invent evidence |
| `create_from_scope --check` returns a handoff | Surface its `nextSkill` and `nextAction` |
| `research-op` rejects | Read the structured rule and repair the payload |
| No legal Experiment remains | Route `HALT_NO_CANDIDATE` and propose a scope decision |
