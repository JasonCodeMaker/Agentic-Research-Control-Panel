---
name: research-op
description: "Use when the user invokes /research-op or needs guarded changes to an existing research package or Scope SSOT: row/card/section edits, inventory field updates, checks/lints, artifact event fanout, registry additions, scope transitions, or natural-language status fixes."
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob
context: fork
disable-model-invocation: false
---

# research-op

## Purpose

The single mutation surface for existing research packages. Replaces direct Edit/Write on package files. Enforces the (category, status, op, target) legality matrix and per-target invariants before any byte hits disk. Appends one audit line per op to a local jsonl log.

## Invocation

Two shapes — structured (autonomous) and natural-language (user).

```bash
# Structured (agent + WORKFLOW.md + scan-events callers)
python skills/research-op/scripts/research_op.py --pkg <id> --op insert --target methodsTried --payload '{...}'
python skills/research-op/scripts/research_op.py --pkg <id> --event CHAIN_DONE --payload '{"artifact": "..."}'
python skills/research-op/scripts/research_op.py --pkg <id> --op check --scope all
python skills/research-op/scripts/research_op.py --pkg <id> --op scan-events
python skills/research-op/scripts/research_op.py --pkg <id> --op scope-transition \
  --payload '{"id":"dir/<id>","level":"direction","parents":["project/main"],"version":1,"status":"ACTIVE","yardstick":{...},"provenance":"txn-0","op":"create","gate":"USER_CROSS_MODEL_AUDIT"}'
# Project-level knowledge registries (papers / edges / gaps) — durable cross-package stores
python skills/research-op/scripts/research_op.py --pkg <id> --op registry-add --target paper \
  --payload '{"id":"dpr2020","title":"Dense Passage Retrieval","url":"https://arxiv.org/abs/2004.04906"}'
python skills/research-op/scripts/research_op.py --pkg <id> --op registry-add --target edge \
  --payload '{"from":"paper:dpr2020","to":"paper:ours","type":"extends","evidence":"we adapt its dual-encoder"}'
python skills/research-op/scripts/research_op.py --pkg <id> --op registry-add --target gap \
  --payload '{"id":"G1","summary":"no zero-shot benchmark for this domain"}'
# Unified rules registry (data/rules.js) — package rules via the package path,
# project rules via the synthetic _project context (needs a human ack), check anywhere
python skills/research-op/scripts/research_op.py --pkg <id> --op insert --target rule \
  --payload '{"level":"package","kind":"binding","slug":"one-notebook","title":"One notebook per figure","text":"Every figure gets its own notebook.","rationale":"reproducibility","addedAt":"2026-06-11"}'
python skills/research-op/scripts/research_op.py --pkg _project --op insert --target rule \
  --payload '{"level":"project","kind":"constraint","slug":"no-eval-leak","title":"No eval leakage","text":"Never train on the eval split.","rationale":"validity","addedAt":"2026-06-11","ack":"<verbatim human approval>"}'
python skills/research-op/scripts/research_op.py --pkg _project --op check --target rule

# Natural-language (user manual fixes)
python skills/research-op/scripts/research_op.py --nl 'update: set status of 2026-05-15-panda-baselines to BLOCKED, reason: GPU contention'
```

## Natural-language handling

`--nl` is an escape hatch: the CLI does **not** parse prose — it returns exit 4 and asks for the structured form. Parsing is the agent's job, done here in the body, so the agent stays the one translator (no brittle regex in the script). To handle an NL fix:

1. Pick the **op** from the leading verb: `set`/`update` → `update`, `add`/`insert` → `insert`, `remove`/`delete` → `delete`, `check`/`lint` → `check`.
2. Read the **package id** (the `YYYY-MM-DD-slug` token in the prose).
3. Read the **target** and the **new value(s)**: e.g. "status of X to BLOCKED" → target `status`, payload `{"to":"BLOCKED"}`; a trailing `reason: …` clause becomes an extra payload field.
4. Echo one preview line back to the user before running: `→ --pkg <id> --op <op> --target <target> --payload <json>`.
5. Run that structured command. On reject, follow [On reject](#on-reject).

## Preconditions

| Precondition | Check |
| --- | --- |
| Package exists | `test -f research_html/packages/<id>/index.html` |
| Inventory entry exists | `grep -q "id: '<id>'" research_html/data/research-packages.js` |
| Runtime root resolved | `RESEARCH_RUNTIME_ROOT` env or default `outputs/<id>/` exists |

## Op surface

Primitives: `insert · update · delete · check`. Composite events: `CHAIN_DONE · CHECKPOINT_SAVED · SENTINEL_WRITE · PHASE_MARKER · CANDIDATE_SUBMITTED`. Full legality matrix in [references/matrix.md](references/matrix.md). Per-event surface map in [references/composite-events.md](references/composite-events.md).

Three ops live outside the `(category, status)` matrix (they are project-level, not package surfaces):

- `scan-events` — read-only artifact scan (no state-gate, no validation) that lists newly-locked facts for the per-turn propagation cycle.
- `scope-transition` — the one gated writer for the Scope SSOT, used by `research-scope` after human ratification. It is gated by the node **level** (project / direction / task), *not* the package state machine, and appends one transition to `outputs/_scope/transitions.jsonl`. The payload carries the node fields (`id, level, parents, version, status, yardstick, provenance`) plus the transition meta (`op, gate, trigger, cause, invalidates, reopens, dial_revert`).
- `registry-add` — the gated writer for the project-level **knowledge registries** (`--target paper | edge | gap`), the durable cross-package stores the Context Pack reads and `context.html` surfaces. Gated by per-target reject-before-write validators (`registry.py`), not the package state machine; dedups and appends one line to `research_html/data/{papers,edges,gaps}.jsonl`. Payloads: **paper** = `{id|arxiv|source_id (≥1 required), title (required), url, pkg}`; **edge** = `{from (required), to (required), type ∈ extends|contradicts|addresses_gap|invalidates (required), evidence}`; **gap** = `{id (required), summary (required), status}`. A duplicate is a silent idempotent skip (still audited). `--pkg` is the adding context (must exist) and is recorded on the audit line.
- `--target rule` with `--pkg _project` — the project-level half of the **unified rules registry** (`data/rules.js`). Package-level rule rows flow the normal state-gated path (`--pkg <pkg-id>`, matrix rows I12/U14/D9); project-level rows use the synthetic `_project` context and require a non-empty `payload.ack` (the distinct human action — research-apply passes its human token through). `level=universal` is write-locked everywhere (the R/T mirror); `origin ∈ {mirror, selfevolve}` rows are export-owned. `--op check --target rule` wraps `learnings_lint.py lint-rules`. Retired targets `package-invariant` / `analysis-rule` reject with a pointer to this target.

## Validate-before-write contract

Every Insert / Update / Delete passes Phase 1 (state gate) and Phase 2 (invariant check) before bytes hit disk. Phase 1 looks up `(category, status, op, target)` in `transitions.py`; Phase 2 runs per-target rules from [references/validate-rules.md](references/validate-rules.md). Reject envelope: `{rejected: true, phase, rule, file, anchor, field, expected, actual, suggested_fix, op, target}`. On reject, the agent retries with the rule visible.

## On reject

Read the structured envelope. The `suggested_fix` field tells you how to adjust the payload. Re-invoke with the corrected payload. Do not bypass — every rejection traces to a real spec invariant.

## Audit log

Path: `outputs/<pkg>/_actions.jsonl`. One JSONL line per op invocation (success or reject). Verbatim payload included. Never tracked in git. `tail -f` is the live-observability surface; `grep '"validation": "OP_REJECTED"'` is the agent-stuck debug surface.

## Single-home invariants this skill protects

1. **Terminal freeze (delete-only)**: a `methodsTried` row cannot be *deleted* once status is in `success/*` or `fail/*` (enforced by `rule_methodstried_terminal_frozen`); appending rows and updating `terminationMessage` stay legal there. `verdict` and `evidencePath` are not independent `--target`s — they are fields inside a `methodsTried` / result-gate row, mutated through those targets, never directly.
2. **Single-home rule**: each Insert has exactly one target file; downstream surfaces re-paint.
3. **Per-event atomicity**: composite events either succeed for every owning surface or fail entirely; no half-written fan-out.

## Pointers

- [references/matrix.md](references/matrix.md) — the 36-row Insert/Update/Delete/Check legality matrix; also encodes the 18-cell (category, status) state machine.
- [references/composite-events.md](references/composite-events.md) — the 5 composite events.
- [references/validate-rules.md](references/validate-rules.md) — Phase 2 invariant catalogue.

## Bundled resources

- `scripts/research_op.py` — CLI entry.
- `scripts/rules_store.py` — data/rules.js load/save + row validation (the registry writer the rule ops use).
- `scripts/transitions.py` — the legality matrix as Python dicts (per-op target maps).
- `scripts/events.py` — 5 composite events.
- `scripts/validate.py` — Phase 2 rules.
- `scripts/router.py` — dispatcher.
- `scripts/audit.py` — jsonl writer.
- `scripts/scan_events.py` — artifact mtime scanner.
- `scripts/ops/{insert,update,delete,check}.py` — per-op handlers.
- `scripts/ops/_pkg_block.py` — HTML package-block parser shared by the insert/update/delete handlers.
