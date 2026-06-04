# Wiki → Trustworthy-Research-Pipeline integration — design & build plan

**Date:** 2026-06-04 · **Status:** approved (brainstorm), implementing all phases
**Source studied:** `.source/existing_work/Auto-claude-code-research-in-sleep` (ARIS) — `skills/research-wiki`, `skills/wiki-enrich`, `tools/research_wiki.py`, the integration-contract + capture-antipatterns shared-refs.

## Principle: replicate the *functions*, not the *files*

ARIS stores entities as markdown pages + a `graph/edges.jsonl` because markdown is its only substrate. We have an HTML+JS dashboard + `research-packages.js`. Recreating the wiki's files beside ours would create **two sources of truth** for the same entity — the exact divergence Problem 1 fights. So every adopted wiki function maps onto a store we already own, or a new store **written through `research-op`** — never a parallel markdown tree.

### Gap analysis (what we already have vs. the real delta)

| Wiki capability | Our analog | Verdict |
| --- | --- | --- |
| `claims/`+`experiments/` verdicts | `research-packages.js` `methodsTried[]` (lint+evidence-gated) | have it, stronger |
| `ideas/` + failed-idea anti-repeat | `research-ideate` scope-conditional banlist | have it, stronger |
| distilled rules | `analysis.html` Rules + `outputs/_learned/rules.md` | have it |
| anti-self-poisoning + producer≠applier | `research-reflect`→`research-apply` jury+human gate | have it, stronger |
| integration contract | `research-op` single mutation surface + readiness gate | have an equivalent |
| **`query_pack` agent context pack** | `learnings.html` is human-only | **GAP** (the spine) |
| **durable cross-package literature** | `outputs/<pkg>/lit/sources.json` ephemeral | **GAP** |
| **typed cross-entity graph** | only implicit links | **GAP** |
| `gap_map` field gaps | none | **GAP (minor)** |

## The Context Pack (the spine — a derived, read-only projection)

To agent-context what `learnings.html` is to the human: a **deterministic, budgeted, evidence-linked** projection of stores we already maintain. No new mutation surface (writes still go through `research-op`); **no LLM in assembly** (a hallucination can't enter at compile time).

**Two tiers:**
- **Project-core** (durable, `research_html/data/context-core.js`, never pruned): cross-package learned Rules + cross-package failed methods + adopted wins. Serves Problem 3 (durable memory) + Problem 2 (human surface source).
- **Direction-overlay** (ephemeral, `outputs/<pkg>/context_pack.{md,json}`, regenerated per loop): active yardstick + this direction's banlist + fetched papers. Serves Problem 1 (per-loop working context).

**Faithfulness guarantees** (the pack is re-injected into context):
1. deterministic (stable order + fixed prune priority → byte-identical re-runs)
2. evidence-linked (every line carries its witnessing anchor)
3. freshness-stamped (`scope_version`+`generated_at`+sources-present; stale iff `scope_version` advanced)
4. injection-scanned (web-sourced lit excerpts → banner on hit, treat embedded directives as DATA)
5. budget with protected floor (Rules + failures never pruned; papers/relationship-detail pruned first)

**Architecture:** `lib/context_pack/` is **pure** (`assemble(inputs, budget) -> ContextPack`, `render_md`, `render_json`, `is_stale`, minimal `scan`) → node-free unit tests. A thin I/O loader (`build`) reads stores (research-packages.js via the canonical node `dump_packages.js`; banlist/sources via JSON; analysis Rules via HTML regex; `_learned/rules.md`; scope log via `scope_ssot`) and writes the artifacts.

## Phase plan (each independently shippable, TDD, conda `python3.13`)

| Phase | Deliverable | Serves |
| --- | --- | --- |
| **0** | `lib/context_pack/` pure assembler + `render_md/json` + `is_stale` + `scan` + CLI `build` writing `context_pack.{md,json}` + `data/context-core.js` | foundation |
| **1** | agent-consumption hooks: `research-auto` Step 0/1 assembles pack; `research-ideate`/`research-lit`/`research-write` read it; staleness regen; backfill CLI | **P1** |
| **2** | `research_html/context.html` read-only "Agent Context" page rendered from `context-core.js` (sibling to `learnings.html`) | **P2** |
| **3** | `detect_cross_package_dead_end` in `research-reflect` (method/idea verdict=fail across N packages) → staged proposal → unchanged `research-apply` gate | **P3** |
| **4** | durable papers registry `data/papers.js` (dedup by source/arxiv id) via `research-op --target paper`; promotes `lit/sources.json`; dashboard list; feeds pack "Key Papers" | P3 |
| **5** | typed-edge graph `data/edges.jsonl` via `research-op --op insert --target edge` + validators (nodes resolve, type∈{extends,contradicts,addresses_gap,invalidates}); derived "Connections" render; feeds pack "Relationships" | **P1** (typed interfaces) |
| **6** | gap registry `data/gaps.js` via `research-op --target gap`; `addresses_gap` edges target it; feeds pack "Open Gaps" | P3 |

Order by value: **0 → 1 → 2 → 3 → 4 → 5 → 6.** Phases 0–3 deliver the full Context-Pack value across all three core problems; 4–6 are the function-parity enrichment. Any phase can stop and leave a coherent system.

## Contracts respected
- Single mutation surface: the pack is derived; new stores (papers/edges/gaps) are written only through `research-op` (reject-before-write validators).
- HCI/HTML: durable knowledge surfaces on the dashboard; Connections is a derived render, never hand-edited.
- Manual analysis untouched: `analysis.html` stays hand-curated; the pack *reads* Rules, never writes them.
- TDD throughout; graceful degradation (missing optional source → assemble from what exists, record present-sources; never hard-fail the loop).

## As-built (2026-06-04) — all phases DONE, TDD, full suite 260 passed (+46)

Two realization choices refined the table above during implementation (both reduce complexity, stay faithful):

- **Registries are plain JSONL** (`research_html/data/{papers,edges,gaps}.jsonl`), not `.js` — written by a new project-level op **`research-op --op registry-add --target {paper,edge,gap}`** (handled inline like `scope-transition`, bypasses the package state-gate; validators + dedup in `skills/research-op/scripts/registry.py`). They are read by `build.py` (no node) and never loaded by HTML directly, so JSONL is simpler than JS and matches the wiki's own `edges.jsonl`.
- **No per-package "Connections" render.** Edges/gaps/papers-registry surface as Context-Pack **core sections** (`relationships` / `open_gaps` / `papers_registry`) → `context-core.js` → rendered by the existing generic `context.html` renderer. One surface, no new render code.

Components shipped: `lib/context_pack/` (`__init__.py` pure assembler + `build.py` loader/CLI) · `skills/research-op/scripts/registry.py` + `--op registry-add` · `context.html` + `assets/research-context.js` + `data/context-core.js` default · `reflect.detect_cross_package_dead_end` + `--context-pack`. Consumers wired (prose): `research-auto` step 1b, `research-ideate` 1b, `research-lit` 1b+step 7, `research-write` step 2, `research-reflect`. Edge types built: `extends/contradicts/addresses_gap/invalidates` (others intentionally skipped). Edge node-resolution is intentionally light (type-validated + dedup, matching ARIS `add_edge`).

## Explicitly NOT built (YAGNI)
- No second mutation surface (`research_wiki.py` analog).
- No parallel markdown entity pages for experiments/claims/ideas (we own them, stronger).
- No two-phase ingest/enrich (our stores are already populated).
- Edge types `tested_by`/`supports` (≈ `evidencePath`) and `supersedes` (already expressed) — skipped.
