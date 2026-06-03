---
name: research-ideate
description: "R3 ideate — the hypothesis role. Use when the auto-research loop needs to propose hypotheses for a scoped direction. Consults a scope-conditional failed-idea banlist (scripts/banlist.py): a failed idea stays banned only while the scope that failed it holds, and is reopened when a metric revise invalidates the old failure condition (via lib/scope_ssot.propagate). Never re-proposes a still-banned idea. Project-agnostic; reads the active yardstick from the active direction node (Scope SSOT-owned intent), using the SSOT transition log only to detect a revise; gated writes route through research-op. Also use when a user asks to brainstorm, ideate, or propose hypotheses for a scoped direction."
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob
context: fork
disable-model-invocation: false
---

# research-ideate (R3 · ideate)

Proposes hypotheses for a scoped direction, then filters them through the **scope-conditional banlist**
so the loop never re-tries an idea that failed under the current scope. A failed idea is not permanent:
when a direction-level metric revise moves the goalpost, `scope_ssot.propagate` identifies which bans
are now stale and the banlist is pruned before filtering — failure is never permanent across a goalpost
move.

## Resources

**Pipeline root**: `/home/uqzzha35/Project/Trustworthy-Research-Pipeline/Trustworthy-Research-Pipeline`

| Asset | Path |
|---|---|
| Scope SSOT lib | `<pipeline-root>/lib/scope_ssot/__init__.py` |
| Banlist CLI | `<pipeline-root>/skills/research-ideate/scripts/banlist.py` |
| research-op CLI | `<pipeline-root>/skills/research-op/scripts/research_op.py` |
| Banlist file | `var/research/<pkg>/ideate/banlist.json` |
| Candidates output | `var/research/<pkg>/ideate/candidates.json` |
| Scope transition log | `var/research/_scope/transitions.jsonl` |

Import pattern for scope_ssot:
```python
import sys
sys.path.insert(0, "<pipeline-root>/lib")
import scope_ssot
```

Banlist CLI usage:
```bash
# Filter candidates against the banlist — prints surviving ids as JSON array
python3 skills/research-ideate/scripts/banlist.py allowed \
  --banlist var/research/<pkg>/ideate/banlist.json \
  --candidates '["id1","id2","id3"]'

# Prune reopened entries from the banlist file — prints a JSON array of kept entry ids
python3 skills/research-ideate/scripts/banlist.py reopen \
  --banlist var/research/<pkg>/ideate/banlist.json \
  --reopened '["id1"]'
```

Banlist file schema — JSON array of entries. `kind` and `failed_on_metric` are **required** for the
reopen logic: `scope_ssot.propagate` only reopens an entry whose `kind == "idea"` and whose
`failed_on_metric` equals the old metric.
```json
{"id": "...", "kind": "idea", "hypothesis": "...", "failed_on_metric": "...", "scope_version": 1, "banned_at": "..."}
```

---

## Procedure

**Step 1 — Get the active yardstick.**

The active direction **node** (with its `yardstick`) is supplied by the orchestrator (`research-auto`)
or, standalone, recovered from the accepted Triage item's `proposed_yardstick` in
`var/research/_scope/triage.jsonl`. Read the metric from that node:

```python
metric = node["yardstick"]["metric"]   # what "failure" is measured against
```

The Scope SSOT transition log is the *timeline*, not a node store: `scope_ssot.read_log(...)` +
`scope_ssot.history("<direction-node-id>", records)` return transition records that each embed the full
post-transition node snapshot at `record["node"]` (the yardstick is recoverable as
`record["node"]["yardstick"]`, but read the active metric from the orchestrator-supplied node). Use the
log to read the current `scope_version` and to detect a metric revise (a record with
`op == "revise"`). The direction yardstick fields are `hypothesis`, `metric`, `baselines`,
`success_predicate`; `metric` + `success_predicate` define what "failure" means and gate which bans stay live.

**Step 2 — Generate N candidate hypotheses (agent creative step).**

Propose N candidate hypotheses for the direction. This is the generative step — reason about the
direction's `hypothesis` and `success_predicate` from Step 1, produce distinct, testable ideas, and
assign each a stable string id (e.g., `hyp-001`, `hyp-002`). Write nothing to disk yet.

Example candidates list:
```json
[
  {"id": "hyp-001", "hypothesis": "Use contrastive pre-training on domain data ..."},
  {"id": "hyp-002", "hypothesis": "Add a re-ranking stage with cross-encoder ..."}
]
```

**Step 3 — Filter candidates through the banlist.**

If `var/research/<pkg>/ideate/banlist.json` does not exist, all candidates survive; skip to Step 5.

Otherwise, extract the candidate ids and call the banlist CLI:

```bash
python3 skills/research-ideate/scripts/banlist.py allowed \
  --banlist var/research/<pkg>/ideate/banlist.json \
  --candidates '["hyp-001","hyp-002"]'
# stdout: ["hyp-001"]  — surviving ids
```

Retain only the candidates whose ids appear in the output. If this turn carries a metric revise, do
Step 4 (reopen stale bans) **before** this filter so a just-reopened idea is not over-blocked — the
post-prune pass is the canonical one.

**Step 4 — On a metric revise, reopen stale bans.**

If the direction's transition timeline shows a recent `op == "revise"` (a goalpost move), the bans that
failed only on the *old* metric should reopen. The old and new metric come from the direction node
before and after the revise (supplied by the orchestrator — they are not stored in the log records):

```python
import json
memory = json.load(open("var/research/<pkg>/ideate/banlist.json"))   # entries carry kind + failed_on_metric
result = scope_ssot.propagate(old_metric=old_metric, new_metric=new_metric, memory=memory)
reopened_ids = result["reopen"]   # ids whose failure condition no longer applies
```

Then prune those entries from the banlist file:

```bash
python3 skills/research-ideate/scripts/banlist.py reopen \
  --banlist var/research/<pkg>/ideate/banlist.json \
  --reopened '["hyp-001"]'
```

Re-run the `allowed` filter (Step 3) after pruning — the pruned ids are now unblocked.

**Step 5 — Write survivors to candidates.json.**

Serialize the surviving candidate objects (id + hypothesis text) to:

```
var/research/<pkg>/ideate/candidates.json
```

Create the `var/research/<pkg>/ideate/` directory if it does not exist.

**Step 6 — Insert brainstorm rows via research-op (only when category=brainstorm, status EXPLORING/PILOT_READY).**

If the package is in category `brainstorm` with status `EXPLORING` or `PILOT_READY` (the only cells where
`brainstorm-section` inserts are legal — `PROMOTED` / `ABANDONED` reject), insert each surviving hypothesis
as a brainstorm row through the single mutation surface:

```bash
python3 skills/research-op/scripts/research_op.py \
  --pkg <pkg-id> \
  --op insert \
  --target brainstorm-section \
  --payload '{"slug": "hyp-001", "title": "<short hypothesis label>", "body": "<full hypothesis text>"}'
```

One call per surviving hypothesis. Do not write directly to HTML package files.

---

## Output Contract

| Artifact | Location | Written by |
|---|---|---|
| Surviving hypotheses | `var/research/<pkg>/ideate/candidates.json` | Step 5 (direct write) |
| Brainstorm surface rows | `research_html/packages/<pkg>/brainstorm.html` | Step 6 via research-op (brainstorm packages only) |
| Pruned banlist | `var/research/<pkg>/ideate/banlist.json` | Step 4 via `banlist.py reopen` |

No other files are written. Never invoke git.

---

## Done Condition

`candidates.json` exists and contains at least one surviving hypothesis. Report the surviving ids and
their hypothesis text to the caller.

---

## Error Path

**All candidates banned (empty survivor set after Step 3/4):** Do not write an empty `candidates.json`.
Report: "All candidates are banned under the current scope. Either propose a scope metric revise via
`research-scope` (which will reopen stale bans on the next ideate pass), or manually unban an entry by
removing it from `var/research/<pkg>/ideate/banlist.json` with justification."

**Direction node not found in transitions.jsonl:** The scope has not been initialized for this direction.
Run `research-scope` to create the direction node before calling research-ideate.

**research-op rejects a brainstorm insert:** The package category is not `brainstorm`, the brainstorm
status is `PROMOTED` or `ABANDONED` (inserts are legal only in `EXPLORING` / `PILOT_READY`), or the payload
is missing `slug` / `title` / `body`. Check the rejection message — it contains the violated rule. Fix the
payload or skip the insert step if the package is `in-progress`.
