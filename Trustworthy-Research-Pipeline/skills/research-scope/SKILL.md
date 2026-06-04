---
name: research-scope
description: "R1 scope + the Task/Objective surface — the scope role. Use when defining or revising a project/direction/task's intent, or when the agent wants to change scope. The agent may only PROPOSE a scope change: it lands as a pending Triage item (scripts/triage.py), never a direct SSOT write — the objective cascade is PM-write-only. The human accepts (committed via research-op's scope-transition op) or rejects (archived, SSOT untouched). Reads/writes intent through lib/scope_ssot; all SSOT writes route through research-op. Never invokes git. Use this skill directly when a user defines or changes scope; research-auto invokes the same R1 role internally during the autonomous loop."
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob
context: fork
disable-model-invocation: false
---

# research-scope (R1 · scope + Triage admission gate)

The agent proposes; the PM disposes. This separation is how "user-monitored" and "autonomous" coexist:
the Scope SSOT is never mutated by agent action alone — every write is either a user-committed
`scope-transition` (accepted Triage item) or rejected with the SSOT left untouched.

## Resources

**Pipeline root:** `/home/uqzzha35/Project/Trustworthy-Research-Pipeline/Trustworthy-Research-Pipeline`

| Resource | Path |
|---|---|
| Scope SSOT lib | `<pipeline-root>/lib/scope_ssot/__init__.py` |
| Triage CLI | `<pipeline-root>/skills/research-scope/scripts/triage.py` |
| Transition log (SSOT commits) | `var/research/_scope/transitions.jsonl` |
| Triage queue (pending/disposed) | `var/research/_scope/triage.jsonl` |
| research-op entrypoint | `<pipeline-root>/skills/research-op/scripts/research_op.py` |
| Milestone planner | `<pipeline-root>/skills/research-scope/scripts/plan_milestones.py` |
| Direction→package materializer | `<pipeline-root>/skills/research-package/scripts/create_from_scope.py` |

Import pattern for the lib:
```python
import sys
sys.path.insert(0, "<pipeline-root>/lib")
import scope_ssot
```

Triage CLI commands:
```bash
# Propose a scope change (agent path)
python3 skills/research-scope/scripts/triage.py propose \
    --log var/research/_scope/triage.jsonl \
    --item '<json>'

# List pending items (agent or human inspection)
python3 skills/research-scope/scripts/triage.py pending \
    --log var/research/_scope/triage.jsonl

# Dispose an item — accept or reject (human PM path)
python3 skills/research-scope/scripts/triage.py dispose \
    --log var/research/_scope/triage.jsonl \
    --id <item-id> \
    --decision accept|reject
```

On accept, the human then commits the transition (agent does NOT do this). The payload must carry all seven node fields **plus** `op` (one of `create` / `revise` / `supersede` / `reopen` / `archive`) and `gate` (the required gate for the node's level — see the gate table below); `research_op.py` reads `op` and `gate` out of the payload and passes them to `scope_ssot.propose_transition`, which rejects a missing/illegal `op` or a mismatched `gate`:
```bash
python3 skills/research-op/scripts/research_op.py \
    --pkg <pkg-id> --op scope-transition \
    --payload '{"id":"dir-retrieval-v2","level":"direction","parents":[],"version":1,"status":"active","yardstick":{...},"provenance":"...","op":"create","gate":"user+xmodel-audit"}'
```

## Node shape

A node has these required fields:

```json
{
  "id": "<unique-string>",
  "level": "project|direction|task",
  "parents": ["<parent-id>"],
  "version": 1,
  "status": "active",
  "yardstick": { ... },
  "provenance": "<free text or reference>"
}
```

Yardstick fields differ by level — supply all fields for the relevant level, no others:

| level | required yardstick fields |
|---|---|
| `project` | `north_star`, `contribution_spine`, `non_goals` |
| `direction` | `hypothesis`, `metric`, `baselines`, `success_predicate` |
| `task` | `experiment`, `config_ref`, `gate_predicate`, `autonomy_level` |

A yardstick must not contain readings (measured values, results, verdicts). Those live in results surfaces, not in scope.

Required gate per level — the `gate` field passed to `scope_ssot.propose_transition`:

| level | gate |
|---|---|
| `project` | `user` |
| `direction` | `user+xmodel-audit` |
| `task` | `agent+async-ack` |

## Procedure

**1. Read active scope.**

```python
import sys; sys.path.insert(0, "<pipeline-root>/lib"); import scope_ssot
records = scope_ssot.read_log("var/research/_scope/transitions.jsonl")
history = scope_ssot.history("<node-id>", records)  # [] if new node
```

If the log does not exist or is empty, there is no committed scope yet — the first proposal creates it.

**2. Validate the proposed node.**

Build the node dict according to the shape above, then call:

```python
scope_ssot.validate_node(node)  # checks level + yardstick field legality only; id/version/parents/status/provenance must also be present (propose_transition relies on them)
```

Fix any `RuleViolation` before proceeding. Do not hand-edit log files to work around a violation.

**3. Build the Triage item.**

The item dict passed to `triage.py propose` must include:

```json
{
  "id": "<unique-item-id>",
  "level": "project|direction|task",
  "change": "<one-sentence description of what changes>",
  "rationale": "<why this change is needed>",
  "proposed_yardstick": { ... },
  "post_accept_actions": []
}
```

For a `level == "direction"` proposal, ask this QA before calling `triage.py propose`:

> This Direction is still a pending proposal. If you accept it into the Scope SSOT, should I then propose high-level validation milestones before any package is generated?

If the user answers yes, set:

```json
"post_accept_actions": ["plan_validation_milestones"]
```

If the user answers no or later, leave `post_accept_actions` empty. Never create the package from a pending Triage item, and never let package surfaces invent high-level validation goals.

**4. Submit the proposal.**

```bash
python3 skills/research-scope/scripts/triage.py propose \
    --log var/research/_scope/triage.jsonl \
    --item '{"id":"scope-001","level":"direction","change":"...","rationale":"...","proposed_yardstick":{...}}'
```

**5. Show pending items to the user and STOP.**

```bash
python3 skills/research-scope/scripts/triage.py pending \
    --log var/research/_scope/triage.jsonl
```

Display the pending list. Do not proceed further. The agent's work ends here — scope commitment is the human PM's decision.

**Human accept path (PM action, not agent):**

1. PM runs `triage.py dispose --decision accept`.
2. PM commits via `research-op --op scope-transition` with gate matching the node's level.
3. The transition is appended to `var/research/_scope/transitions.jsonl`.
4. If the accepted item has `post_accept_actions` containing `plan_validation_milestones`, ask one short confirmation: "Direction is now committed. Propose high-level validation milestones for it?" On yes, invoke `plan_milestones.py` with the committed direction node id. On no, stop and report that `plan_milestones.py --direction-id <direction-id>` can be run later.

Milestone proposal command:

```bash
python3 skills/research-scope/scripts/plan_milestones.py \
    --direction-id <direction-node-id> \
    --transitions var/research/_scope/transitions.jsonl \
    --triage var/research/_scope/triage.jsonl
```

After the PM accepts/revises those milestone proposals and commits each Task/Milestone node with `research-op --op scope-transition`, ask: "Milestones are now committed. Generate the research package from the Direction plus accepted milestones?" On yes, invoke the materializer:

```bash
python3 skills/research-package/scripts/create_from_scope.py \
    --direction-id <direction-node-id> \
    --root research_html \
    --transitions var/research/_scope/transitions.jsonl
```

**Human reject path:** PM runs `triage.py dispose --decision reject`. The item is archived in `triage.jsonl`; the SSOT is untouched.

Example — proposing a direction node:

```bash
python3 skills/research-scope/scripts/triage.py propose \
    --log var/research/_scope/triage.jsonl \
    --item '{
      "id": "dir-retrieval-v2",
      "level": "direction",
      "change": "Narrow retrieval target to zero-shot cross-modal setting only",
      "rationale": "In-distribution results are at ceiling; zero-shot gap is the open problem",
      "proposed_yardstick": {
        "hypothesis": "Cross-modal zero-shot R@1 can reach 48 without supervised fine-tuning",
        "metric": "R@1 on MSRVTT zero-shot split",
        "baselines": ["CLIP-zero-shot=42.3"],
        "success_predicate": "R@1 >= 48 on held-out seed"
      },
      "post_accept_actions": ["plan_validation_milestones"]
    }'
```

## Output contract

| Path | Written by | Contents |
|---|---|---|
| `var/research/_scope/triage.jsonl` | Agent (propose) + PM (dispose) | Pending and disposed Triage items, including optional post-accept milestone-planning intent, one JSON object per line |
| `var/research/_scope/transitions.jsonl` | PM only (via research-op scope-transition) | Committed scope transitions, one JSON object per line |
| `var/research/<pkg>/_actions.jsonl` | research-op | Audit line for every scope-transition op |

The agent appends to `triage.jsonl` only. It never writes to `transitions.jsonl` directly.

## Done condition

The skill is done when the pending Triage item is visible in `triage.jsonl`, has been shown to the user, and any direction-level milestone-planning QA has been answered and recorded in `post_accept_actions`. The scope change is not yet in effect — it takes effect only after PM acceptance and the `research-op --op scope-transition` commit. Package files are created only after the Direction and its accepted high-level validation milestones are committed.

## Error path

| Error | Meaning | Action |
|---|---|---|
| `RuleViolation` from `validate_node` | The node dict violates the schema (missing field, wrong level, reading in yardstick, etc.) | Fix the node dict and retry `validate_node` before calling `triage.py propose`. Never hand-edit the log. |
| `RuleViolation` from `scope_ssot.propose_transition` (human path) | The transition op was refused by the gate check | Confirm the `gate` value matches `REQUIRED_GATE[node.level]` and retry. |
| `triage.py propose` exits non-zero | Item JSON is malformed, or the `id` key is missing (the script enforces only `id`) | Check the `--item` JSON parses and carries `id`. `level`, `change`, `rationale`, and `proposed_yardstick` are required by this contract (downstream consumers need them) but are not validated by the script — include them anyway. |
| Triage item sits pending indefinitely | PM has not disposed it | Surface the pending list again; do not re-propose the same change. |
