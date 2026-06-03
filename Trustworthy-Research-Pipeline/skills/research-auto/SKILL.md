---
name: research-auto
description: "The auto-research orchestrator — drives one research direction's idea->paper loop through the seven roles (R1 scope, R2 search/read, R3 ideate, R4 experiment, R5 verify, R6 write, R7 remember) and the real trust gates. Use whenever the user types /research-auto or asks to run the autonomous research loop on a scoped direction. Stage 1 = a thin walking skeleton (scripts/skeleton.py) that proves the loop composes end-to-end at the Supervised autonomy level with L1 gates; the heavy roles, the L2 cross-model verifier, the per-task autonomy dial (scripts/dial.py) and the PACK continuity bundle (scripts/pack.py) already ship as tested utilities, and later build stages wire them all into the main loop. Reads every yardstick from the Scope SSOT (lib/scope_ssot); every gated write routes through research-op. Never invokes git."
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob
context: fork
disable-model-invocation: false
---

# research-auto

## Purpose

The orchestrator skill. It does not own any mutation surface or yardstick of its own: it pulls intent
from the Scope SSOT (`lib/scope_ssot`), dispatches the seven research roles, and routes every gated
write through `research-op`. It is the journey-step actuator for **Run** in the usage spine.

The trust guarantee: no claim reaches the paper unless its citation resolves on disk (L1 cite-exists),
and the direction is never marked acquitted unless the metric oracle clears the SSOT success predicate.

## Resources

`<pipeline-root>` = `/home/uqzzha35/Project/Trustworthy-Research-Pipeline/Trustworthy-Research-Pipeline`

| Asset | Path |
| --- | --- |
| Walking skeleton | `skills/research-auto/scripts/skeleton.py` |
| Autonomy dial | `skills/research-auto/scripts/dial.py` |
| PACK continuity | `skills/research-auto/scripts/pack.py` |
| Scope SSOT lib | `lib/scope_ssot/__init__.py` |
| Cite-check lib | `lib/cite_check/__init__.py` |
| Verifier lib | `lib/verifier/__init__.py` |
| Scope transition log | `var/research/_scope/transitions.jsonl` |
| Triage queue | `var/research/_scope/triage.jsonl` |
| Per-package audit log | `var/research/<pkg>/_actions.jsonl` |

Import pattern: `sys.path.insert(0, "<pipeline-root>/lib"); import scope_ssot`.

research-op CLI:
```bash
python3 skills/research-op/scripts/research_op.py --pkg <id> --op <op> --target <target> --payload '<json>'
```

## Stage 1 — the walking skeleton (R1..R7)

`scripts/skeleton.py` runs one thin `idea -> paper` pass through all seven roles at the **Supervised**
autonomy level. Each role is thin or a stub; what is real is the wiring:

- **R1 scope** writes a typed Direction node into the SSOT via the gated writer
  (`scope_ssot.propose_transition`, `op=create`, the direction change-gate).
- **R2 search/read** runs the **L1 cite-exists** check — a citation whose source does not resolve on
  disk is rejected and never reaches the paper.
- **R3 ideate** adopts the direction hypothesis as the idea under test (stub).
- **R4 experiment** is a toy metric (the base `WORKFLOW.md` experiment loop is reused later).
- **R5 verify** is the **L1 metric oracle**: it reads the success predicate back from the SSOT
  yardstick and compares the measured value.
- **R6 write** is a **grounded-only** IMRAD skeleton — only verified facts and verified citations appear.
- **R7 remember** + the terminal **acquit** routes through research-op's `acquit-needs-verdict` gate at
  Supervised (a `T1:supervised-ack`); the acquit is **blocked** whenever the metric oracle fails.

Run the Stage-1 gate:

```bash
python3 -m pytest tests/research-auto/test_skeleton.py -q
```

## Invoking the skeleton

`skeleton.run` signature:

```python
skeleton.run(
    intent,            # str — the research question or direction hypothesis
    *,
    pkg_id,            # str — package id, e.g. "2026-06-03-demo"
    runtime_root,      # str — path under var/research/<pkg>
    citations,         # list of {"id": str, "source": <file path on disk>}
    measured,          # float — the experiment metric value to check against the yardstick
)
```

Returns a dict with keys: `chain`, `idea`, `yardstick`, `verdict`, `verified_citations`,
`rejected_citations`, `acquitted`, `ack_token`, `paper_path`.

Writes on exit:
- `<runtime_root>/run.json` — the full run record
- `<runtime_root>/paper.md` — the grounded IMRAD skeleton
- `<runtime_root>/_scope/transitions.jsonl` — the skeleton's own transition log (Stage-1, per-run). The
  *shared* project scope log used by `research-op --op scope-transition` (and read by `research-scope` /
  `research-reflect`) is `var/research/_scope/transitions.jsonl`; pass `runtime_root=var/research` if you
  want the skeleton to append to that shared log instead.

Runnable example:

```bash
python3 -c "
import sys; sys.path.insert(0, 'skills/research-auto/scripts')
import skeleton
result = skeleton.run(
    'contrastive pretraining improves recall',
    pkg_id='2026-06-03-demo',
    runtime_root='var/research/2026-06-03-demo',
    citations=[{'id': 'smith2024', 'source': 'docs/smith2024.txt'}],
    measured=0.86,
)
print(result['acquitted'])
"
```

## Bundled utilities (available now)

### dial.py — per-task autonomy dial

```python
import sys; sys.path.insert(0, 'skills/research-auto/scripts'); import dial
```

`dial.revert_on_scope_change(tasks, transition) -> tasks`

When a direction- or project-level scope transition fires, this reverts every Task listed in
`transition["dial_revert"]` to `autonomy_level="supervised"` and locks it. Task-level transitions
do not trigger a revert. Use this whenever the transition record's `dial_revert` list is non-empty
(`scope_ssot.propose_transition` always returns `dial_revert` as a list — `[]` when nothing reverts).

### pack.py — PACK continuity bundle

```python
import sys; sys.path.insert(0, 'skills/research-auto/scripts'); import pack
```

`PACK_FIELDS = ("attempted", "found", "hypothesis_state", "next_action", "blocking_decision")`

- `pack.missing_fields(bundle) -> list` — returns any PACK_FIELDS not present or blank in `bundle`.
- `pack.write_pack(pack_log, bundle)` — rejects (raises) before writing if any field is blank; appends the bundle to `pack_log` (a jsonl path).
- `pack.latest(pack_log) -> dict | None` — returns the last bundle written to `pack_log`, or `None` if the log is absent or contains no records.

When running at Async or Autonomous autonomy, call `pack.write_pack` on each loop tick so an absent
reader is never left with a silent gap.

## Procedure — driving one direction's loop

1. **Load scope.** The direction node (with its yardstick) is the input you iterate — built by R1 /
   `research-scope`, or, for the skeleton, constructed by `skeleton.scope(intent, pkg_id)` and validated
   by the gated writer. `scope_ssot.read_log("var/research/_scope/transitions.jsonl")` +
   `scope_ssot.history(node_id, records)` give the transition *timeline* (versions/ops), not the
   yardstick — read `node["yardstick"]` from the node itself. A `RuleViolation` from the gated writer
   means the yardstick is malformed; stop and surface it.

2. **Check autonomy.** Read the task's `autonomy_level`. If Async or Autonomous, confirm a PACK log
   path is set; you will write a bundle on every tick.

3. **Run the skeleton.** Call `skeleton.run(intent, pkg_id=..., runtime_root=..., citations=..., measured=...)`.
   This executes R1–R7 and returns the run record.

4. **Inspect the verdict.**
   - `result["acquitted"] == True` → proceed to step 5.
   - `result["acquitted"] == False` → the metric oracle failed. Do not transition status. Write the
     run record path and `result["verdict"]` to the user. Stop the loop for this direction until the
     user intervenes or the measured value changes.

5. **Propagate gated writes.** Route every surface mutation through research-op:
   ```bash
   python3 skills/research-op/scripts/research_op.py --pkg <id> --op <op> --target <target> --payload '<json>'
   ```
   Scope SSOT writes use `--op scope-transition`. Never call `Edit`/`Write` directly on package surfaces.

6. **Dial revert check.** If the scope transition record carries `dial_revert`, call
   `dial.revert_on_scope_change(tasks, transition)` and update the affected tasks via research-op.

7. **PACK tick (Async/Autonomous only).** Assemble a PACK bundle covering the current tick and call
   `pack.write_pack(pack_log, bundle)`. This raises before writing if any field is blank — fix the
   bundle before continuing.

8. **Report.** Emit: acquit status, `run.json` path, `paper.md` path, any rejected citations, and
   the ack token if user ack is pending.

## Output contract

| Output | Location |
| --- | --- |
| Run record | `<runtime_root>/run.json` (e.g. `var/research/<pkg>/run.json`) |
| Grounded paper skeleton | `<runtime_root>/paper.md` |
| Skeleton transition log | `<runtime_root>/_scope/transitions.jsonl` (Stage-1, per-run) |
| Shared scope log | `var/research/_scope/transitions.jsonl` (written by research-op `--op scope-transition`) |
| Per-package audit line | `var/research/<pkg>/_actions.jsonl` (written by research-op) |
| PACK bundle (Async/Autonomous) | `var/research/<pkg>/_pack.jsonl` (or caller-supplied path) |

The orchestrator writes nothing directly to package HTML surfaces — those go through research-op.

## Done condition

The loop is complete when `result["acquitted"] == True` and the direction's `status` has been
transitioned (via research-op `scope-transition`) to a terminal state, or when the direction is
archived. At Supervised autonomy, the user ack token in `result["ack_token"]` must be confirmed
before the acquit is recorded.

## Error & stop conditions

| Condition | Meaning | Action |
| --- | --- | --- |
| `scope_ssot.validate_node` raises `RuleViolation` | Yardstick is malformed (e.g., a `measured` reading was stored in the node) | Stop. Surface the violation message. Do not run the loop. |
| `result["acquitted"] == False` | Metric oracle failed — measured value did not clear the success predicate | Do not transition status. Surface `run.json` verdict to the user. Wait for intervention. |
| `pack.write_pack` raises | A PACK field is blank | Fix the bundle before the tick closes. A silent gap is a trust violation. |
| Citations rejected by R2 | A citation's `source` file does not resolve on disk | `skeleton.search_read` partitions by disk-existence of `c["source"]`; rejected ids are in `result["rejected_citations"]` and excluded from the paper — report them. (The Stage-2b `cite_check.unresolved_citations` tool is a different schema keyed on `source_id`.) |
| Direction archived | `scope_ssot.history` returns a record with `op == "archive"` | Stop. The direction is closed. Surface the archive message. |

## Later stages (not yet wired into the main loop)

Stage 2a adds the L2 cross-model verifier (`lib/verifier`) into R5, replacing the toy metric oracle
with `verifier.jury_request` + `verifier.assess_acquit`. Stage 2b makes each role heavy and delegates
to the split skills (`research-scope` / `research-lit` / `research-ideate` / `research-write`).
Stage 2c wires the already-built `dial.py` and `pack.py` into the main loop dispatch (they are tested
utilities today but not yet called by `skeleton.run`). Stage 3 adds the self-learning loop via
`research-reflect` + `research-apply`.
