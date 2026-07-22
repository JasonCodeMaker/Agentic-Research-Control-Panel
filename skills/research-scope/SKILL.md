---
name: research-scope
description: "Use when defining, revising, accepting, or rejecting governed Project, Direction, or Experiment intent."
---

# Research scope

Turn natural-language intent into one hash-bound Scope decision. The agent
prepares the semantic review; only an explicit user decision may commit or
reject it.

Keep governance strict behind the interface. Users review semantic content,
not proposal ids, hashes, NoteRefs, event ids, or CLI syntax.

## Authority

`.research/state` owns proposals and committed Scope. `.research/interface` is
a disposable read model and must not be read or edited as authority.

The hierarchy is:

```text
Project -> Direction -> Experiment
```

## Where Scope belongs in the lifecycle

Project Scope is established during onboarding because it defines the durable
workspace boundary. Direction and Experiment Scope are different: they freeze
research intent only after the Draft Package document has been refined enough
for the user and agents to share one clear proposal.

```text
Project Scope
  -> standalone Brainstorm + refinement
  -> agent materializes the requested idea as Package lifecycle=DRAFT
  -> Draft refinement and one Direction-and-Experiments review
  -> one user approval atomically commits Scope and lifecycle=ACTIVE
```

Scope is therefore a commit boundary, not an early authoring form. Do not force
a vague Brainstorm into fixed fields merely to create a Package shell. The
non-executable Draft is an authoring container, while the single Scope Bundle
approval freezes Direction and Experiments and activates it.

## Decompose a Direction into Experiments

Treat an Experiment as the smallest independently governable evidence
contract. It is not a phase name, task list, metric, method arm, seed, retry,
or convenient scheduling unit. A Direction may need one Experiment or many;
never assume a fixed count or generate a standard milestone roster.

Before creating or revising Experiment proposals, read
[`references/experiment-decomposition.md`](references/experiment-decomposition.md)
completely and apply its decision ledger, split test, merge test, and coverage
check. Preserve these core rules:

- Split when the decision, protocol or configuration family, evidence-admission
  rule, lifecycle, or independently interpretable evidence differs.
- Merge only when partial completion would not create an ambiguous or
  misleading result and all governance semantics are shared.
- Represent baselines and treatments as arms, metrics as observables, seeds and
  retries as Runs, and setup work as implementation tasks inside the owning
  Experiment.
- Put a performance threshold in `gate` only when the ratified Direction calls
  for that scientific decision rule. Record-only characterization uses an
  evidence-completeness gate.
- Do not invent dependency edges for execution order. Record a dependency only
  when upstream evidence changes whether the downstream Experiment is
  admissible or interpretable.

Show the resulting Experiment map and Direction coverage before asking the
user to ratify any proposal. `scripts/plan_milestones.py` accepts only explicit
evidence-contract input; it must never invent semantic decomposition from a
Direction alone.

| Level | Required spec | Gate |
|---|---|---|
| `project` | `goal`, `contributions`, `out_of_scope` | `USER_ONLY` |
| `direction` | `hypothesis`, `metric`, `baselines`, `success_gate` | `USER_CROSS_MODEL_AUDIT` |
| `experiment` | `purpose`, `config_ref`, `gate`, `control_mode` | `AGENT_DEFERRED_ACK` |

Measured values, verdicts, Run status, and result readings never belong in a
Scope spec. Validate complete nodes with `lib/scope_ssot`; never bypass a
rejection by editing state.

Text limits remain part of validation:

- Project `goal`: 3 to 100 words; each list item: 5 to 50 words.
- Direction `hypothesis` and `success_gate`: 20 to 100 words; each baseline:
  5 to 50 words; `metric`: a non-empty object or 20 to 100 words.
- Experiment `purpose` and `gate`: 20 to 100 words; `config_ref`: non-empty;
  `control_mode`: `SUPERVISED`, `CHECKPOINTED`, `DEFERRED`, or `AUTONOMOUS`.

## Human contract

- Show one complete semantic review after preparing the bound content.
- Accept natural-language decisions such as `CONFIRM`, `ACCEPT`, `确认`, or
  `接受` when they clearly refer to that review.
- Treat requested changes as revision, not acceptance.
- Treat a generic, stale, conflicting, or multiply bound reply as ambiguous.
- Do not require the user to copy an item id or hash.
- Reveal technical receipts only when requested.

Review digests and, on the compatibility path, item ids and proposal hashes
remain internal bindings to the exact content visible to the user. They must
still match at the gateway.

## Prepare and review

For a normal Draft Package, validate the complete Direction and every selected
Experiment, then prepare one Scope Bundle through `research-package
review-scope`. Do not create a Proposal aggregate or accept the components
separately. Independent later Scope revisions may still use the compatibility
Proposal fields and Triage commands.

A Direction created from a Draft Package must also include an exact
`source_package` object:

```json
{
  "id": "<package-id>",
  "draft_revision": 3,
  "document_sha256": "<reviewed-document-hash>"
}
```

Review and commit both revalidate this binding. If the draft changes after the
visible review, reject the stale approval and prepare a new review; never
silently bind the newer document.

```bash
python3 skills/research-package/scripts/draft_package.py \
  --workspace . review-scope \
  --package-id <package-id> \
  --direction '<complete-direction-node>' \
  --experiments '<complete-experiment-node-array>'
```

Review creates no state. Keep its receipt internal and show:

Keep the compact receipt internal. Show:

```markdown
**Scope review**
- Package and operation: <plain language>
- Direction: <every semantic Direction field exactly as proposed>
- Experiments: <every selected Experiment and its four-field spec>
- Parent: <plain language, when applicable>
- Effect on existing Scope: <invalidations, reopenings, or none>
- Assumptions: <material assumptions, or none>
- Decision: reply CONFIRM/确认, describe revisions, or REJECT/拒绝
```

Do not show the same full review again after confirmation.

## Decision paths

### Accept

For a normal Draft Package, `research-package` owns the Scope Bundle review and
commit. An explicit user confirmation authorizes the exact Draft to become
`SCOPE_READY`, commits Direction and Experiments, activates the same Package,
and opens its Execution Lease. Invoke its combined transaction command with the
hidden receipt:

```bash
python3 skills/research-package/scripts/draft_package.py \
  --workspace . commit-scope \
  --package-id <package-id> \
  --direction '<reviewed-direction-node>' \
  --experiments '<reviewed-experiment-array>' \
  --review-sha256 <internal-receipt-digest> \
  --actor-id <stable-user-id> \
  --review-id <conversation-review-id>
```

The kernel checks the user actor, review binding, Draft revision and NoteRef,
Direction and Experiment gates, participant versions, and idempotency. It
writes one `TransactionCommitted` event or nothing. Retry the same command after
an infrastructure interruption; do not ask the user to approve again.

Project onboarding uses `research-onboard`. For an independently governed later
Scope change not coupled to Draft activation, use the Proposal/Triage
compatibility path with ordinary `scope-accept` and `--pkg _scope`.

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace . --pkg _scope --op scope-accept \
  --from-triage <proposal-id> --proposal-hash <proposal-hash> \
  --actor-type user --actor-id <stable-user-id>
```

### Revise

Apply the requested semantic changes to the complete node, validate it, and
submit a replacement under the same proposal id. Show the replacement once.
Do not accept or commit the old snapshot.

### Reject

Record `REJECTED` through `triage.py dispose` using the hidden id and hash with
an explicit user actor. Rejection changes no committed Scope.

## Low-level compatibility path

`triage.py dispose` followed by `research-op --op scope-transition
--from-triage <proposal-id>` remains supported for repair, diagnostics, and
separately governed callers. Ordinary conversational approval uses
`scope-accept`. A `package_finalization` proposal cannot use this path because
separate proposal, Scope, and Package events would violate its atomic approval
boundary.

The explicit payload form is reserved for separately governed structured
callers. It cannot substitute for or bypass the accepted snapshot.

## Direction follow-up

For a new Draft Package, finish Experiment decomposition before preparing the
full Scope Bundle. Do not accept a Direction first and generate
Experiment proposals afterward. Later independent Scope revisions may still
use their level-specific gates and ordinary Scope commands.

## Done condition

For Draft finalization, the user made one explicit semantic decision and one
event left the same Package `ACTIVE / CONTEXT_LOADED` with the exact Direction
and Experiments committed. For revision, one replacement is pending and
visible. For rejection, the proposal is disposed and committed Scope is
unchanged. Every path remains event-backed and auditable.
