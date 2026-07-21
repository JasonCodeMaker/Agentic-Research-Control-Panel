---
name: research-scope
description: "Use when defining or revising governed Project, Direction, or Experiment intent."
---

# research-scope

The agent proposes; the PM decides. A proposal does not change research intent.
Only an explicit, hash-bound PM decision can dispose it:

- `ACCEPT <item-id> <proposal-hash>` authorizes the `ACCEPTED` disposition and
  the gated `research-op` Scope writer.
- `REJECT <item-id> <proposal-hash>` authorizes only the `REJECTED`
  disposition.
- `REVISE <item-id> <proposal-hash>` authorizes a validated replacement under
  the same item id. It authorizes neither a disposition nor a Scope write.

The item id and hash must match the exact proposal visible to the PM. A stale
hash, ambiguous reply, or missing decision leaves the proposal pending. Never
infer or manufacture a PM decision. Never invoke git.

If the user cannot yet state a Direction as
`hypothesis / metric / baselines / success_gate`, use
`/research-brainstorm` first.

## Authority and commands

`.research/state` is the management authority. `.research/interface` is a
disposable human projection and must not be read as Scope state. Skills never
edit state JSON, events, audit rows, HTML, JavaScript, or CSV directly.

All commands resolve the workspace through `ResearchPaths`. Use
`--research-root` only when the workspace does not use the default
`.research` root.

```bash
# Read committed intent through a bounded query
python3 -m lib.research_state.cli --workspace . show project
python3 -m lib.research_state.cli --workspace . show direction
python3 -m lib.research_state.cli --workspace . show experiment

# Inspect proposals
python3 skills/research-scope/scripts/triage.py --workspace . pending

# Submit a validated proposal
python3 skills/research-scope/scripts/triage.py --workspace . propose \
  --item '<proposal-json>'

# Record an explicit, matching PM decision
python3 skills/research-scope/scripts/triage.py --workspace . dispose \
  --id <item-id> \
  --decision ACCEPTED|REJECTED \
  --proposal-hash <proposal-hash> \
  --actor-type user \
  --actor-id <pm-id>
```

`triage.py` calls the typed `research-op` management gateway. It never owns a
separate proposal store. Omitting the actor flags records the caller as an
agent, so the disposition is rejected and the proposal remains pending.

## Scope node contract

Every proposal carries a complete `proposed_node`:

```json
{
  "id": "<stable-id>",
  "level": "project|direction|experiment",
  "parents": ["<parent-id>"],
  "version": 1,
  "status": "ACTIVE",
  "spec": {},
  "source": "<user dialogue or evidence reference>"
}
```

A Project has no parent. A Direction has a Project parent. An Experiment has a
Direction parent and may carry `package_id` when a Package already exists.

| Level | Required spec | Gate |
|---|---|---|
| `project` | `goal`, `contributions`, `out_of_scope` | `USER_ONLY` |
| `direction` | `hypothesis`, `metric`, `baselines`, `success_gate` | `USER_CROSS_MODEL_AUDIT` |
| `experiment` | `purpose`, `config_ref`, `gate`, `control_mode` | `AGENT_DEFERRED_ACK` |

Text constraints:

- Project `goal`: 3 to 100 words.
- Direction `hypothesis` and `success_gate`: 20 to 100 words.
- Experiment `purpose` and `gate`: 20 to 100 words.
- Each Project list item and Direction baseline: 5 to 50 words.
- `metric` is a non-empty object or a 20 to 100 word string.
- `config_ref` is a non-empty reference.
- `control_mode` is `SUPERVISED`, `CHECKPOINTED`, `DEFERRED`, or
  `AUTONOMOUS`.

Measured values, verdicts, Run status, and result readings never belong in a
Scope spec.

Validate the complete node before submission:

```python
import sys
sys.path.insert(0, "<pipeline-root>/lib")
import scope_ssot

scope_ssot.validate_node(node)
```

Do not bypass `RuleViolation` by editing a state file.

## Proposal contract

The item submitted to `triage.py propose` contains:

```json
{
  "id": "<proposal-id>",
  "level": "project|direction|experiment",
  "node_id": "<proposed-node-id>",
  "op": "create|revise|supersede|reopen|archive",
  "gate": "<required-level-gate>",
  "change": "<one sentence>",
  "rationale": "<why this change is needed>",
  "proposed_spec": {},
  "proposed_node": {},
  "post_accept_actions": []
}
```

For a Direction proposal, ask whether the PM wants high-level validation
Experiments proposed after acceptance. If yes, record
`"post_accept_actions": ["plan_validation_experiments"]`. Pending proposals are
collision warnings, not accepted intent.

The explicit payload form is reserved for separately governed structured
callers. It cannot substitute for or bypass the accepted snapshot when
executing a ratified Triage proposal.

## Review before submission

Show the exact content before asking the PM to confirm submission:

```markdown
**Scope Review**
- Status: Candidate, not yet submitted
- Level: project | direction | experiment
- Node: <node-id>
- Parents: <parent ids>
- Operation / Gate: <operation> / <gate>
- Spec: <every field exactly as it would enter state>
- Source: <source>
- Rationale: <rationale>
- Post-Accept Actions: <actions or []>
- Next Step: CONFIRM to submit, REVISE with changes, or REJECT the draft
```

If the user supplied exact wording, reproduce it verbatim in the Spec section.
Keep agent interpretation outside the proposed spec.

After confirmation, submit the item and show the returned proposal hash:

```markdown
**Scope Review**
- Status: Pending Triage, not yet committed
- Triage Item: <item-id>
- Proposal Hash: <proposal-hash>
- Level: project | direction | experiment
- Node: <node-id>
- Parents: <parent ids>
- Operation / Gate: <operation> / <gate>
- Spec: <every field exactly as submitted>
- Rationale: <rationale>
- Post-Accept Actions: <actions or []>
- Next Step: Reply `ACCEPT <item-id> <proposal-hash>`, `REVISE <item-id> <proposal-hash>` with changes, or `REJECT <item-id> <proposal-hash>`
```

Without an explicit PM decision, stop here.

## Decision paths

### Accept

After the PM replies with the exact visible item id and proposal hash:

1. Re-read pending proposals and verify both values.
2. Record the accepted disposition with `triage.py dispose`.
3. Commit only the accepted snapshot:

   ```bash
   python3 skills/research-op/scripts/research_op.py \
     --workspace . \
     --pkg _scope \
     --op scope-transition \
     --from-triage <item-id>
   ```

Delegated execution of a ratified Triage proposal must use
`--from-triage <item-id>`.

The gateway revalidates the proposal hash, level gate, node version, and
idempotency before writing Project, Direction, or Experiment state.

If an accepted Direction requested validation planning, ask one short
confirmation. On yes:

```bash
python3 skills/research-scope/scripts/plan_milestones.py \
  --workspace . \
  --direction-id <direction-id>
```

The command submits five governed Experiment proposals. Each still requires
its own visible, hash-bound PM decision. Once the relevant Experiments are
accepted, check package readiness from state:

```bash
python3 skills/research-package/scripts/create_from_scope.py \
  --workspace . \
  --direction-id <direction-id> \
  --check --json
```

### Reject

Verify the visible item id and hash, then record `REJECTED`. The proposal leaves
the pending view and committed Scope state remains unchanged.

### Revise

Verify the visible item id and hash. Apply the requested field changes to the
complete node, validate it, and submit a replacement under the same item id.
Show the replacement in full with its new hash. Do not dispose the old view or
invoke the Scope writer for `REVISE`.

## Done condition

For a pending proposal, the exact review and hash are visible and no committed
intent changed. For acceptance, both the accepted disposition and the
hash-bound `scope-transition` succeed. For rejection, no Project, Direction,
or Experiment aggregate changes. For revision, the new same-id proposal is
pending with a new visible hash.

Every command outcome is recorded under `.research/audit`; state changes are
events under `.research/state`. The interface can be deleted and rebuilt
without changing any of these decisions.
