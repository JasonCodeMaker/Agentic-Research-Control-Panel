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

# Natural-language (user manual fixes)
python skills/research-op/scripts/research_op.py --nl 'update: set status of 2026-05-15-panda-baselines to BLOCKED, reason: GPU contention'
```

The skill body parses natural-language prose into the structured form, prints the resolved form back as a preview line, then dispatches to the same script.

## Preconditions

| Precondition | Check |
| --- | --- |
| Package exists | `test -f research_html/packages/<id>/index.html` |
| Inventory entry exists | `grep -q "id: '<id>'" research_html/data/research-packages.js` |
| Runtime root resolved | `RESEARCH_RUNTIME_ROOT` env or default `var/research/<id>/` exists |

## Op surface

Primitives: `insert · update · delete · check`. Composite events: `chain-done · checkpoint-saved · sentinel-write · phase-marker · candidate-json`. Full legality matrix in [references/matrix.md](references/matrix.md). Per-event surface map in [references/composite-events.md](references/composite-events.md).

## Validate-before-write contract

Every Insert / Update / Delete passes Phase 1 (state gate) and Phase 2 (invariant check) before bytes hit disk. Phase 1 looks up `(category, status, op, target)` in `transitions.py`; Phase 2 runs per-target rules from [references/validate-rules.md](references/validate-rules.md). Reject envelope: `{rejected: true, phase, rule, file, anchor, field, expected, actual, suggested_fix}`. On reject, the agent retries with the rule visible.

## On reject

Read the structured envelope. The `suggested_fix` field tells you how to adjust the payload. Re-invoke with the corrected payload. Do not bypass — every rejection traces to a real spec invariant.

## Audit log

Path: `var/research/<pkg>/_actions.jsonl`. One JSONL line per op invocation (success or reject). Verbatim payload included. Never tracked in git. `tail -f` is the live-observability surface; `grep '"validation": "rejected"'` is the agent-stuck debug surface.

## Single-home invariants this skill protects

1. **Terminal freeze**: `methodsTried`, `terminationMessage`, `verdict`, `evidencePath` are immutable once status crosses into `success/*` or `fail/*`.
2. **Single-home rule**: each Insert has exactly one target file; downstream surfaces re-paint.
3. **Per-event atomicity**: composite events either succeed for every owning surface or fail entirely; no half-written fan-out.

## Pointers

- [references/matrix.md](references/matrix.md) — the 33-row Insert/Update/Delete/Check legality matrix.
- [references/composite-events.md](references/composite-events.md) — the 5 composite events.
- [references/validate-rules.md](references/validate-rules.md) — Phase 2 invariant catalogue.
- [references/state-machine.md](references/state-machine.md) — 18-cell (category, status) machine + T1 ack rules.

## Bundled resources

- `scripts/research_op.py` — CLI entry.
- `scripts/transitions.py` — 33-row matrix as Python dict.
- `scripts/events.py` — 5 composite events.
- `scripts/validate.py` — Phase 2 rules.
- `scripts/router.py` — dispatcher.
- `scripts/audit.py` — jsonl writer.
- `scripts/scan_events.py` — artifact mtime scanner.
- `scripts/ops/{insert,update,delete,check}.py` — per-op handlers.
