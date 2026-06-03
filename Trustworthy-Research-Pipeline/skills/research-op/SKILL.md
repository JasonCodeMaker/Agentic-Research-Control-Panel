---
name: research-op
description: "The single mutation surface for any existing research package. Use whenever the user types /research-op, asks to insert/update/delete a row/card/section in a package (methodsTried, result-gate, result block, tracker row, doc card, doc file, brainstorm section), asks to update an inventory field (status, activeGate, primaryMetricVsGate, lastAction, terminationMessage, adoptionPath), asks to check/lint a package, asks to fan out an artifact event (chain-done, checkpoint-saved, sentinel-write, phase-marker, candidate-json). Also use for ad-hoc natural-language fixes like 'set status of <pkg> to BLOCKED'. Project-agnostic. Hard requirement: target package must exist (run /research-package first). Init is owned by /research-package and /research-dashboard, not this skill. Every write goes through a (category, status, op, target) state gate plus per-target invariant validators; on reject no bytes hit disk and the agent receives a structured rule violation. Every successful or rejected op appends one JSONL line to var/research/<pkg>/_actions.jsonl. Never invokes git."
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
python skills/research-op/scripts/research_op.py --pkg <id> --event chain-done --payload '{"artifact": "..."}'
python skills/research-op/scripts/research_op.py --pkg <id> --op check --scope all
python skills/research-op/scripts/research_op.py --pkg <id> --op scan-events
python skills/research-op/scripts/research_op.py --pkg <id> --op scope-transition \
  --payload '{"id":"dir/<id>","level":"direction","parents":["project/main"],"version":1,"status":"active","yardstick":{...},"provenance":"txn-0","op":"create","gate":"user+xmodel-audit"}'

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
| Runtime root resolved | `RESEARCH_RUNTIME_ROOT` env or default `var/research/<id>/` exists |

## Op surface

Primitives: `insert · update · delete · check`. Composite events: `chain-done · checkpoint-saved · sentinel-write · phase-marker · candidate-json`. Full legality matrix in [references/matrix.md](references/matrix.md). Per-event surface map in [references/composite-events.md](references/composite-events.md).

Two ops live outside the `(category, status)` matrix:

- `scan-events` — read-only artifact scan (no state-gate, no validation) that lists newly-locked facts for the per-turn propagation cycle.
- `scope-transition` — the one gated writer for the Scope SSOT, used by `research-scope` / `research-auto`. It is gated by the node **level** (project / direction / task), *not* the package state machine, and appends one transition to `var/research/_scope/transitions.jsonl`. The payload carries the node fields (`id, level, parents, version, status, yardstick, provenance`) plus the transition meta (`op, gate, trigger, cause, invalidates, reopens, dial_revert`).

## Validate-before-write contract

Every Insert / Update / Delete passes Phase 1 (state gate) and Phase 2 (invariant check) before bytes hit disk. Phase 1 looks up `(category, status, op, target)` in `transitions.py`; Phase 2 runs per-target rules from [references/validate-rules.md](references/validate-rules.md). Reject envelope: `{rejected: true, phase, rule, file, anchor, field, expected, actual, suggested_fix, op, target}`. On reject, the agent retries with the rule visible.

## On reject

Read the structured envelope. The `suggested_fix` field tells you how to adjust the payload. Re-invoke with the corrected payload. Do not bypass — every rejection traces to a real spec invariant.

## Audit log

Path: `var/research/<pkg>/_actions.jsonl`. One JSONL line per op invocation (success or reject). Verbatim payload included. Never tracked in git. `tail -f` is the live-observability surface; `grep '"validation": "rejected"'` is the agent-stuck debug surface.

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
- `scripts/transitions.py` — the legality matrix as Python dicts (per-op target maps).
- `scripts/events.py` — 5 composite events.
- `scripts/validate.py` — Phase 2 rules.
- `scripts/router.py` — dispatcher.
- `scripts/audit.py` — jsonl writer.
- `scripts/scan_events.py` — artifact mtime scanner.
- `scripts/ops/{insert,update,delete,check}.py` — per-op handlers.
- `scripts/ops/_pkg_block.py` — HTML package-block parser shared by the insert/update/delete handlers.
