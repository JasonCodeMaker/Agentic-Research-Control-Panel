---
name: research-write
description: "R6 write — the paper role. Use when the auto-research loop turns verified results into an IMRAD paper for a scoped direction. Grounded-only: every paper claim must map to a verified artifact id, enforced deterministically by lib/cite_check.ungrounded_claims before write; every citation must resolve (lib/cite_check). A claim with no backing artifact never reaches the paper. Project-agnostic; reads the active yardstick from the active direction node (Scope SSOT-owned intent), using the SSOT transition log only to detect a revise; gated writes route through research-op. Also use when a user asks to draft, write up, or compose the paper/report for a direction's verified results."
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob
context: fork
disable-model-invocation: false
---

# research-write (R6 · write)

The paper role. It composes IMRAD prose, but a claim enters the paper only if it is **grounded**: `lib/cite_check.ungrounded_claims(claims, verified_artifact_ids)` must return empty, and `lib/cite_check.unresolved_citations(citations, fetched_source_ids)` must also return empty. Any claim or citation that does not resolve is stripped and reported — never silently kept. This guarantees that the paper records only what was measured and verified, not what was assumed or recalled.

## Resources

Pipeline root: `/home/uqzzha35/Project/Trustworthy-Research-Pipeline/Trustworthy-Research-Pipeline`

- `lib/cite_check/__init__.py` — the mandatory groundedness + citation gates
- `lib/scope_ssot/__init__.py` — transition timeline (`read_log` / `history`); used only to detect a revise / read `scope_version`, **not** to read the yardstick (the yardstick is on the direction node)
- `skills/research-op/scripts/research_op.py` — single mutation surface for package surfaces

```bash
# Import pattern — cite_check is the mandatory gate; scope_ssot only for timeline checks
python3 -c "import sys; sys.path.insert(0, '<pipeline-root>/lib'); import cite_check"
# add 'import scope_ssot' only when inspecting the transition timeline (detect a revise / scope_version)
```

Paper output path: `outputs/<pkg>/paper/paper.md`
Per-package audit log: `outputs/<pkg>/_actions.jsonl`

## Procedure

### 1. Get the active yardstick

The active direction **node** (with its `yardstick`) is supplied by the orchestrator (`research-auto`)
or, standalone, recovered from the accepted Triage item's `proposed_yardstick` in
`outputs/_scope/triage.jsonl` (the Triage queue written by `research-scope` — verify the field
name against the active record). Read it from that node:

```python
yardstick = node["yardstick"]   # {hypothesis, metric, baselines, success_predicate}
```

The Scope SSOT transition log is the audit *timeline*, not a node store: `scope_ssot.read_log(...)` +
`scope_ssot.history("<direction-node-id>", records)` return transition records that each embed the full
post-transition node snapshot at `record["node"]` (the yardstick is recoverable as
`record["node"]["yardstick"]`). Prefer the orchestrator-supplied active node over hand-parsing the log;
use the log only for the `scope_version` or to detect a revise (`op == "revise"`).

The result claims in the paper must anchor on `yardstick["metric"]` and `yardstick["success_predicate"]`. Do not introduce metrics outside the declared yardstick.

### 2. Draft the IMRAD sections

Produce a draft covering all seven sections. Use the yardstick fields to constrain scope:

| Section | Grounding anchor |
|---|---|
| Title | direction hypothesis |
| Abstract | metric + success_predicate outcome |
| Introduction | hypothesis + baselines |
| Method | experiment + config_ref from task yardstick |
| Results | verified artifact ids from R5 (verifier outputs) |
| Discussion | success_predicate evaluation, limitations |
| References | fetched source ids from research-lit (R2) |

### 3. Collect claims and citations

Build two lists from the draft:

```python
claims = [
    {"id": "c1", "artifact_id": "<verified-artifact-id>"},
    # one entry per factual claim in Results / Discussion
]
citations = [
    {"id": "ref1", "source_id": "<source-id-from-research-lit>"},
    # one entry per reference in References section
]

verified_artifact_ids = [...]   # artifact ids confirmed sound by lib/verifier (R5)
fetched_source_ids    = [...]   # source ids fetched and stored by research-lit (R2)
```

### 4. Run both cite_check gates — required before any write

```python
import sys; sys.path.insert(0, "<pipeline-root>/lib")
import cite_check

ungrounded   = cite_check.ungrounded_claims(claims, verified_artifact_ids)
unresolved   = cite_check.unresolved_citations(citations, fetched_source_ids)
```

- If either list is non-empty: **strip** those claims/citations from the draft, log what was removed, and return to step 2 to revise the affected sections. Do not weaken the check or retain the item with a caveat.
- Repeat the draft → check → strip loop until both lists are empty.
- Example of a strip report: `"Removed claim c3 (artifact_id='run42-checkpoint' not in verified set); removed ref7 (source_id='arxiv:2301.00001' not fetched by research-lit)."`

### 5. Write the paper

Once both checks return empty, write the paper directly to the runtime path. The paper is a
`outputs` artifact, not a package HTML surface, so it is a direct write (`Write` is in
allowed-tools) — there is no research-op "paper" target:

```python
import json, pathlib
pathlib.Path("outputs/<pkg>/paper").mkdir(parents=True, exist_ok=True)
pathlib.Path("outputs/<pkg>/paper/paper.md").write_text(paper_markdown)
pathlib.Path("outputs/<pkg>/paper/claim_map.json").write_text(json.dumps(
    [{"claim_id": c["id"], "artifact_id": c["artifact_id"], "section": "Results"} for c in claims],
    indent=2))
```

If a verified result must *also* be surfaced on the package's `results.html`, that is a separate write
through research-op with the real results targets (`--target results-block` / `results-verdict`), owned
by the results/verify step — not part of writing `paper.md` here.

## Output contract

| Artifact | Path |
|---|---|
| Paper draft | `outputs/<pkg>/paper/paper.md` |
| Claim-to-artifact map | `outputs/<pkg>/paper/claim_map.json` |
| Results surfacing (optional) | via research-op `--target results-block` / `results-verdict`, which appends the audit line to `outputs/<pkg>/_actions.jsonl` |

## Done condition

The skill is done when:
1. `cite_check.ungrounded_claims(claims, verified_artifact_ids)` returns `[]`
2. `cite_check.unresolved_citations(citations, fetched_source_ids)` returns `[]`
3. `outputs/<pkg>/paper/paper.md` exists and contains all seven IMRAD sections
4. `outputs/<pkg>/paper/claim_map.json` exists with one entry per Results/Discussion claim

## Error path

| Condition | Meaning | Action |
|---|---|---|
| `ungrounded_claims` non-empty | A claim's `artifact_id` was not produced by a verified R5 run | Strip the claim, revise that section, re-run both checks |
| `unresolved_citations` non-empty | A citation's `source_id` was never fetched by research-lit | Strip the citation or trigger research-lit (R2) to fetch it first, then re-run |
| Yardstick node not found in scope log | The direction has not been scoped yet | Run research-scope first; do not proceed |
| research-op rejects a results surface write (only if surfacing) | The `(category, status, op, target)` is not legal at this stage | Check the legality in research-op; resolve the gate before retrying |

Do not substitute a weaker check (e.g., accepting claims with "likely" backing). The empty-list exit condition is the only valid exit from the draft→revise loop.
