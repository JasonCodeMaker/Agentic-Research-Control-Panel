---
name: research-scope
description: "Use when defining, revising, accepting, or rejecting governed Project, Direction, or Experiment intent."
---

# Research scope

Turn natural-language intent into one hash-bound Scope decision. The agent may
submit a proposal; only an explicit user decision may accept or reject it.

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
  -> user-approved conversion to Package lifecycle=DRAFT
  -> Draft refinement and one Direction-and-Experiments review
  -> one user approval atomically commits Scope and lifecycle=ACTIVE
```

Scope is therefore a commit boundary, not an early authoring form. Do not force
a vague Brainstorm into fixed fields merely to create a Package shell. The
first approval creates that non-executable Draft shell; the later full proposal
freezes Direction and Experiments while activating it.

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

- Show one complete semantic review after proposal submission.
- Accept natural-language decisions such as `CONFIRM`, `ACCEPT`, `确认`, or
  `接受` when they clearly refer to that review.
- Treat requested changes as revision, not acceptance.
- Treat a generic, stale, conflicting, or multiply bound reply as ambiguous.
- Do not require the user to copy an item id or hash.
- Reveal technical receipts only when requested.

The item id and hash remain internal bindings to the exact proposal visible to
the user. They must still match at the gateway.

## Propose and review

Build and validate a complete proposal with `id`, `level`, `node_id`, `op`,
`gate`, `change`, `rationale`, `proposed_spec`, `proposed_node`, and
`post_accept_actions`. A normal Draft Package finalization proposal also uses
`proposal_kind=package_finalization` and includes every selected complete
Experiment node in `proposed_experiments`. Then submit it before asking the
user to decide.

A Direction created from a Draft Package must also include an exact
`source_package` object:

```json
{
  "id": "<package-id>",
  "draft_revision": 3,
  "document_sha256": "<reviewed-document-hash>"
}
```

Submission and finalization both revalidate this binding. If the draft changes
after the visible review, reject the stale approval and prepare a new review;
never silently bind the newer document.

```bash
python3 skills/research-scope/scripts/triage.py --workspace . propose \
  --item '<proposal-json>' --receipt
```

Submission creates only a pending proposal. It does not change Project,
Direction, or Experiment intent, so it needs no prior confirmation.

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

For a Draft Package finalization proposal, an explicit user confirmation
authorizes the exact Draft to become `SCOPE_READY`, accepts the full Scope
bundle, commits Direction and Experiments, and activates the same Package.
Invoke one combined gateway call with the hidden receipt:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace . --pkg <package-id> --op package-finalize \
  --from-triage <proposal-id> --proposal-hash <proposal-hash> \
  --actor-type user --actor-id <stable-user-id>
```

The gateway checks the user actor, pending status, content hash, Draft revision
and NoteRef, Direction and Experiment gates, participant versions, and
idempotency. It appends one `PackageActivated` event or nothing. If projection
failed after commit, retry the same command; do not ask the user to approve
again.

For Project onboarding or an independently governed later Scope change not
coupled to Draft activation, use ordinary `scope-accept` with `--pkg _scope`.

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

For a new Draft Package, finish Experiment decomposition before submitting the
full finalization proposal. Do not accept a Direction first and generate
Experiment proposals afterward. Later independent Scope revisions may still
use their level-specific gates and ordinary Scope commands.

## Done condition

For Draft finalization, the user made one explicit semantic decision and one
event left the same Package `ACTIVE / CONTEXT_LOADED` with the exact Direction
and Experiments committed. For revision, one replacement is pending and
visible. For rejection, the proposal is disposed and committed Scope is
unchanged. Every path remains event-backed and auditable.
