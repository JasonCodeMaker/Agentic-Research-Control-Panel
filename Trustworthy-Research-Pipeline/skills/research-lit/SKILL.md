---
name: research-lit
description: "R2 search/read — the literature role. Use when the auto-research loop needs to find and read sources for a scoped direction. Fetch-don't-fabricate: every citation must resolve to a fetched source, enforced deterministically by lib/cite_check.unresolved_citations before any cite is written. Never invents a source it did not fetch. Project-agnostic; reads the active yardstick from the active direction node (Scope SSOT-owned intent), using the SSOT transition log only to detect a revise; gated writes route through research-op. Also use when a user directly asks to find, survey, or read related work / prior art for a scoped direction."
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob, WebFetch, WebSearch
context: fork
disable-model-invocation: false
---

# research-lit (R2 · search/read)

The trust guarantee is mechanical: a citation is only valid if its `source_id` resolves to a
fetched source. `lib/cite_check.unresolved_citations` enforces this before any write reaches a
package surface, so a fabricated citation cannot propagate into the record.

## Resources

**Pipeline root:** `/home/uqzzha35/Project/Trustworthy-Research-Pipeline/Trustworthy-Research-Pipeline`

| Resource | Path |
| --- | --- |
| cite_check lib | `<pipeline-root>/lib/cite_check/__init__.py` |
| scope_ssot lib | `<pipeline-root>/lib/scope_ssot/__init__.py` |
| research-op script | `<pipeline-root>/skills/research-op/scripts/research_op.py` |
| Fetched sources (output) | `var/research/<pkg>/lit/sources.json` |
| Citations (output) | `var/research/<pkg>/lit/citations.json` |

Import pattern:
```python
import sys
sys.path.insert(0, "<pipeline-root>/lib")
import scope_ssot, cite_check
```

## Procedure

### 1. Get the active yardstick to bound the search

The active direction **node** (with its `yardstick`) is supplied by the orchestrator (`research-auto`)
or, standalone, recovered from the accepted Triage item's `proposed_yardstick` in
`var/research/_scope/triage.jsonl`. Read the yardstick from that node:

```python
yardstick = node["yardstick"]   # {hypothesis, metric, baselines, success_predicate}
```

The Scope SSOT transition log is the audit *timeline*, not a node store: `scope_ssot.read_log(...)` +
`scope_ssot.history("<direction-node-id>", records)` return transition records that each embed the full
post-transition node snapshot at `record["node"]` (so the yardstick is recoverable as
`record["node"]["yardstick"]`, and `scope_ssot.intent(node_id, records)` folds it). Prefer the
orchestrator-supplied active node over hand-parsing the log; use the log only to read the current
`scope_version` or detect a revise (a record with `op == "revise"`).

```python
records = scope_ssot.read_log("var/research/_scope/transitions.jsonl")
revised = any(r["op"] == "revise" for r in scope_ssot.history(node_id, records))
```

Extract `hypothesis`, the `metric` name, and `baselines` — these bound what you search for; do not
search beyond the declared direction.

### 2. Form WebSearch queries from the yardstick

Compose 2–4 queries using `yardstick["metric"]` and key noun phrases from `yardstick["hypothesis"]`.
Run each query with the WebSearch tool. Collect candidate result URLs.

Example query pattern: `"<metric-name> benchmark <domain keyword> 2023 OR 2024"`.

### 3. Fetch each promising result and record it

For each candidate URL, use WebFetch to retrieve the page. Assign a stable `source_id` (e.g.,
`"src-001"`, `"src-002"`) to each successfully fetched page. Collect into a `fetched` list:

```python
fetched = [
    {"source_id": "src-001", "title": "...", "url": "...", "fetched_at": "<iso-ts>", "excerpt": "..."},
    # one entry per fetched page
]
```

Only pages you actually fetched get a `source_id`. If a fetch fails, discard that candidate.

### 4. Build the citations list

For each fetched source that is relevant to the direction, create a citation entry. A citation's
`source_id` must match an entry in `fetched`:

```python
citations = [
    {"id": "cit-001", "source_id": "src-001"},
    {"id": "cit-002", "source_id": "src-002"},
]
```

Never add a citation whose `source_id` you cannot point to in `fetched`.

### 5. Run the cite_check gate — abort on any unresolved citation

This is the hard gate. Run it before writing anything to disk:

```python
import cite_check

fetched_ids = [s["source_id"] for s in fetched]
unresolved = cite_check.unresolved_citations(citations, fetched_ids)
if unresolved:
    raise SystemExit(f"CITE-GATE REJECT: citations {unresolved} have no fetched source. Drop or refetch.")
```

If `unresolved` is non-empty, drop those citation entries (or refetch their sources) and re-run
the gate. Do not paper over the error by inventing a source.

### 6. Write the deliverable

Only after `unresolved_citations` returns an empty list, write the two JSON artifacts. These are the
lit role's deliverable and the input to `research-write` (R6) — the role that actually surfaces
citations into the paper. They are `var/research` runtime artifacts, written directly (`Write` is in
allowed-tools):

```python
import json, pathlib
pathlib.Path("var/research/<pkg>/lit").mkdir(parents=True, exist_ok=True)
pathlib.Path("var/research/<pkg>/lit/sources.json").write_text(
    json.dumps({s["source_id"]: s for s in fetched}, indent=2))
pathlib.Path("var/research/<pkg>/lit/citations.json").write_text(
    json.dumps(citations, indent=2))
```

If a fetched source should *also* appear on a package surface as a docs page, that goes through
research-op as a single doc-file op (`--op insert --target doc-file`), which atomically creates both the
HTML file and its paired card — do not issue a separate `--target doc-card` op afterward, and never a
direct HTML edit. In the auto-loop, though, citations flow into the paper via `research-write`, not onto
a package page here.

## Output contract

| File | Content |
| --- | --- |
| `var/research/<pkg>/lit/sources.json` | Dict keyed by `source_id`; each value: `{source_id, title, url, fetched_at, excerpt}` |
| `var/research/<pkg>/lit/citations.json` | List of `{id, source_id}` — only entries that passed the gate |
| Package docs page (optional) | Only via `research-op --op insert --target doc-file` (paired card created atomically — no separate doc-card op) |

## Done condition

`cite_check.unresolved_citations(citations, fetched_ids)` returns `[]` and `citations.json` is
written to `var/research/<pkg>/lit/citations.json`.

## Error path

| Situation | Meaning | What to do |
| --- | --- | --- |
| `unresolved_citations` returns non-empty ids | Those citations have no fetched source — writing them would be fabrication | Drop the listed citations, or go back to step 3 and actually fetch those sources; then re-run the gate |
| WebFetch fails for a URL | That URL cannot be a source | Discard it; do not assign it a `source_id` |
| Scope SSOT has no direction node for `<pkg>` | Search is unbounded — proceeding would ignore the yardstick contract | Stop; ask the user to confirm the direction node id or run `research-scope` first |
| `research-op` rejects a `doc-file` insert (only if surfacing a docs page) | The package state gate rejects the write (doc-file is legal only in `brainstorm/*` and `in-progress/*` cells), or the path does not match `research_html/packages/<pkg>/docs/<slug>.html` (rule `doc-file-path-under-package`) | Read the rejection reason from research-op stdout and resolve it before retrying |
