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
`post_accept_actions`. Then submit it before asking the user to decide:

```bash
python3 skills/research-scope/scripts/triage.py --workspace . propose \
  --item '<proposal-json>' --receipt
```

Submission creates only a pending proposal. It does not change Project,
Direction, or Experiment intent, so it needs no prior confirmation.

Keep the compact receipt internal. Show:

```markdown
**Scope review**
- Level and operation: <plain language>
- Parent: <plain language, when applicable>
- Proposed intent: <every semantic field exactly as proposed>
- Effect on existing Scope: <invalidations, reopenings, or none>
- Assumptions: <material assumptions, or none>
- Decision: reply CONFIRM/确认, describe revisions, or REJECT/拒绝
```

Do not show the same full review again after confirmation.

## Decision paths

### Accept

An explicit user confirmation authorizes both the `ACCEPTED` disposition and
the commit of that exact snapshot. Invoke one combined gateway call with the
hidden receipt:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace . --pkg _scope --op scope-accept \
  --from-triage <proposal-id> --proposal-hash <proposal-hash> \
  --actor-type user --actor-id <stable-user-id>
```

The gateway checks the user actor, pending status, content hash, level gate,
node version, accepted snapshot, causation, and idempotency. If acceptance was
recorded but projection or commit completion failed, retry the same command;
do not ask the user to approve again.

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
`scope-accept` to avoid duplicate commands and receipts.

The explicit payload form is reserved for separately governed structured
callers. It cannot substitute for or bypass the accepted snapshot.

## Direction follow-up

If an accepted Direction requested
`post_accept_actions: ["plan_validation_experiments"]`, ask one short question
before creating validation Experiment proposals. Each resulting Experiment
still needs its own gate-appropriate decision.

## Done condition

For acceptance, the user made one explicit semantic decision and the bound
Scope transition succeeded. For revision, one replacement is pending and
visible. For rejection, the proposal is disposed and committed Scope is
unchanged. Every path remains event-backed and auditable.
