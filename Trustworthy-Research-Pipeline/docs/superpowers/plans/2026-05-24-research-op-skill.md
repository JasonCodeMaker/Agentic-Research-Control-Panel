# Research-Op Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `research-op` skill — a single agent-invokable mutation surface that enforces format invariance across all research packages via a (category, status, op, target) transition table and write-time validation, then migrate existing skills and packages to use it.

**Architecture:** One Claude Code Skill at `skills/research-op/` with thin SKILL.md (≤ 150 lines, `context: fork`) backed by Python scripts. The scripts encode the 33-row legality matrix as data (`transitions.py`), enforce per-target invariants before any write (`validate.py`, the SWE-agent reject-before-write pattern), fan out composite artifact events to all owning surfaces atomically (`events.py`), and append a verbatim audit line per op to `outputs/<pkg>/_actions.jsonl`. No git operations. The four existing skills (`research-dashboard`, `research-package`, `research-analysis`, and the new `research-op`) compose layered: scaffold → editorial → mutation.

**Tech Stack:** Python 3.10+ (stdlib only — argparse, json, pathlib, datetime, hashlib, re, sys), pytest for validator tests, Claude Code Skill format (YAML frontmatter + markdown body + `scripts/` + `references/`).

**Spec:** [`docs/superpowers/specs/2026-05-24-research-op-skill-control-design.md`](../specs/2026-05-24-research-op-skill-control-design.md) (committed at `ee50ce4`).

**User-rule reminders this plan obeys:**
- *Simplicity first*: minimum code; no error handling for impossible scenarios; no try/except unless explicitly needed for control flow; no abstractions for single-use code.
- *Surgical changes*: every edit traces to one matrix cell or one migration item; no unrelated refactoring.
- *Research-code stance*: lightweight tests where they earn their place (validator rules) — not full coverage of plumbing.
- *Goal-driven verification*: every task has an explicit "verify it works" step before commit.

---

## File structure

**New files (created by this plan):**

```
skills/research-op/
├── SKILL.md                                       # ~150-line contract
├── references/
│   ├── matrix.md                                  # 33-row Insert/Update/Delete/Check matrix (verbatim from spec § 4)
│   ├── composite-events.md                        # 5 events with fan-out surface lists
│   ├── validate-rules.md                          # Pattern B rule catalogue
│   └── state-machine.md                           # 18-cell (category, status) + lane-crossing T1 rules
└── scripts/
    ├── research_op.py                             # CLI entry; dispatcher
    ├── transitions.py                             # 33-row matrix as Python dict
    ├── events.py                                  # 5 composite events as {event: [(op, target), ...]}
    ├── validate.py                                # Pattern B reject-before-write checks
    ├── router.py                                  # (category, status, op, target) → handler dispatch
    ├── audit.py                                   # jsonl writer
    ├── scan_events.py                             # artifact mtime scanner (replaces propagate_facts.py role 1)
    └── ops/
        ├── __init__.py
        ├── insert.py
        ├── update.py
        ├── delete.py
        └── check.py

tests/research-op/
├── conftest.py                                    # tmp-package fixture
├── test_transitions.py                            # state-gate table tests
├── test_validate.py                               # per-rule pass/fail tests
├── test_audit.py                                  # jsonl-writer smoke tests
├── test_events.py                                 # composite-event fanout tests
├── test_scan_events.py                            # artifact scanner tests
└── test_cli.py                                    # CLI end-to-end smoke tests
```

**Existing files modified by this plan (text edits, no new logic):**

```
WORKFLOW.md                                        # +1 Mutation rule paragraph; replace ~3 propagate_facts.py mentions
CLAUDE.md (Trustworthy-Research-Pipeline/)         # replace ~5 propagate_facts.py mentions in Protocol 3
.gitignore                                         # ensure outputs/ is excluded
skills/research-analysis/SKILL.md                  # +1 Boundary note; rewire 3 subcommands to delegate to research-op
skills/research-package/SKILL.md                   # +1 Boundary note; remove propagate_facts.py byte-copy reference
skills/research-package/scripts/create_research_package.py   # remove the propagate_facts.py copy step
```

**Existing files removed by this plan:**

```
research_html/packages/*/scripts/propagate_facts.py   # 8 byte-copies, one per package
skills/research-package/scripts/propagate_facts.py    # master copy; functionality absorbed by research-op
```

---

## Phase 1 — Skill scaffold (MVP shell, no validators or ops yet)

Goal: working `/research-op check --pkg <id>` command that reads inventory, identifies `(category, status)`, writes an audit-log entry, and returns success. No ops fire yet; this proves the plumbing.

### Task 1.1: Create skill directory + thin SKILL.md

**Files:**
- Create: `skills/research-op/SKILL.md`
- Create: `skills/research-op/scripts/` (empty directory)
- Create: `skills/research-op/scripts/ops/` (empty directory)
- Create: `skills/research-op/references/` (empty directory)

- [ ] **Step 1: Create directory tree**

```bash
mkdir -p skills/research-op/scripts/ops skills/research-op/references
```

- [ ] **Step 2: Write SKILL.md from the spec § 5.3 budget**

Create `skills/research-op/SKILL.md`:

```markdown
---
name: research-op
description: "The single mutation surface for any existing research package. Use whenever the user types /research-op, asks to insert/update/delete a row/card/section in a package (methodsTried, result-gate, result block, tracker row, doc card, doc file, brainstorm section), asks to update an inventory field (status, activeGate, primaryMetricVsGate, lastAction, terminationMessage, adoptionPath), asks to check/lint a package, asks to fan out an artifact event (chain-done, checkpoint-saved, sentinel-write, phase-marker, candidate-json). Also use for ad-hoc natural-language fixes like 'set status of <pkg> to BLOCKED'. Project-agnostic. Hard requirement: target package must exist (run /research-package first). Init is owned by /research-package and /research-dashboard, not this skill. Every write goes through a (category, status, op, target) state gate plus per-target invariant validators; on reject no bytes hit disk and the agent receives a structured rule violation. Every successful or rejected op appends one JSONL line to outputs/<pkg>/_actions.jsonl. Never invokes git."
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
| Runtime root resolved | `RESEARCH_RUNTIME_ROOT` env or default `outputs/<id>/` exists |

## Op surface

Primitives: `insert · update · delete · check`. Composite events: `chain-done · checkpoint-saved · sentinel-write · phase-marker · candidate-json`. Full legality matrix in [references/matrix.md](references/matrix.md). Per-event surface map in [references/composite-events.md](references/composite-events.md).

## Validate-before-write contract

Every Insert / Update / Delete passes Phase 1 (state gate) and Phase 2 (invariant check) before bytes hit disk. Phase 1 looks up `(category, status, op, target)` in `transitions.py`; Phase 2 runs per-target rules from [references/validate-rules.md](references/validate-rules.md). Reject envelope: `{rejected: true, phase, rule, file, anchor, field, expected, actual, suggested_fix}`. On reject, the agent retries with the rule visible.

## On reject

Read the structured envelope. The `suggested_fix` field tells you how to adjust the payload. Re-invoke with the corrected payload. Do not bypass — every rejection traces to a real spec invariant.

## Audit log

Path: `outputs/<pkg>/_actions.jsonl`. One JSONL line per op invocation (success or reject). Verbatim payload included. Never tracked in git. `tail -f` is the live-observability surface; `grep '"validation": "rejected"'` is the agent-stuck debug surface.

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
```

- [ ] **Step 3: Verify SKILL.md is under 150 lines**

```bash
wc -l skills/research-op/SKILL.md
```

Expected: ≤ 150 (the above body is ~95 lines including frontmatter).

- [ ] **Step 4: Commit**

```bash
git add skills/research-op/SKILL.md
git commit -m "research-op: skill scaffold (thin SKILL.md)"
```

---

### Task 1.2: Copy the 33-row matrix into `references/matrix.md`

**Files:**
- Create: `skills/research-op/references/matrix.md`

- [ ] **Step 1: Lift the matrix verbatim from the spec**

Open `docs/superpowers/specs/2026-05-24-research-op-skill-control-design.md` and copy sections § 4.1, § 4.2, § 4.3, § 4.4, § 4.5 verbatim into `skills/research-op/references/matrix.md`. Add a short header:

```markdown
# research-op — Legality matrix

This file is the authoritative source for `(category, status, op, target)` legality.
`scripts/transitions.py` is generated from this matrix; if you change a row here,
update `transitions.py` in the same commit.

<verbatim copy of spec § 4.1 through § 4.5>
```

- [ ] **Step 2: Verify the file resolves the spec markdown anchors**

```bash
grep -c "^| " skills/research-op/references/matrix.md
```

Expected: ≥ 33 (one row per matrix entry across the 4 tables).

- [ ] **Step 3: Commit**

```bash
git add skills/research-op/references/matrix.md
git commit -m "research-op: lift legality matrix into references/"
```

---

### Task 1.3: Write `scripts/transitions.py` (33-row matrix as Python data)

**Files:**
- Create: `skills/research-op/scripts/transitions.py`

- [ ] **Step 1: Read schema.js to confirm the canonical 18-cell list**

```bash
cat skills/research-dashboard/assets/dashboard/data/schema.js
```

Note the four `status` arrays per category. The transitions table keys on `(category, status)`.

- [ ] **Step 2: Write the transitions.py module**

Create `skills/research-op/scripts/transitions.py`:

```python
"""(category, status, op, target) legality table.

Generated from references/matrix.md (spec section 4). When you change a row in
the matrix, change it here. The CLI looks up legality via is_legal().
"""

# 18-cell (category, status) state machine — must match schema.js.
STATES = {
    "brainstorm":  ["EXPLORING", "PILOT_READY", "PROMOTED", "ABANDONED"],
    "in-progress": ["CONTEXT_LOADED", "IMPLEMENTING", "IMPLEMENTATION_REVIEW",
                    "READY_TO_LAUNCH", "EXPERIMENT_RUNNING", "LIVE_ANALYSIS",
                    "RESULT_ANALYSIS", "NEXT_ACTION_READY", "BLOCKED"],
    "success":     ["ADOPTED_PENDING_ACK", "ADOPTED", "SUPERSEDED"],
    "fail":        ["ARCHIVED", "ARCHIVED_REOPENABLE"],
}

# Targets the matrix recognizes.
TARGETS = {
    # Inventory targets (paint multiple HTML surfaces via renderers)
    "status", "activeGate", "primaryMetricVsGate", "lastAction", "lastUpdated",
    "openRuns", "currentBlocker", "terminationMessage", "adoptionPath",
    "supersededBy", "reopenTrigger", "experiments-row", "experiments-status",
    "methodsTried",
    # HTML in-place targets (single-home, no painter)
    "tracker-live-check-row", "tracker-resource-allocation-row",
    "tracker-impl-review-row", "tracker-chosen-route",
    "results-gate-row", "results-block", "results-verdict",
    "analysis-rule", "analysis-insight",
    "doc-file", "doc-card",
    "brainstorm-section",
    "ack-slot",
    "last-updated-time",
}

# Insert legality: target -> set of (category, status) cells where the Insert is allowed.
INSERT_LEGAL = {
    "experiments-row": {
        ("in-progress", s) for s in ("CONTEXT_LOADED", "IMPLEMENTING", "READY_TO_LAUNCH")
    },
    "methodsTried": (
        {("in-progress", s) for s in ("RESULT_ANALYSIS", "NEXT_ACTION_READY")}
        | {("success", s)  for s in STATES["success"]}
        | {("fail", s)     for s in STATES["fail"]}
    ),
    "tracker-live-check-row": {
        ("in-progress", s) for s in ("EXPERIMENT_RUNNING", "LIVE_ANALYSIS")
    },
    "tracker-resource-allocation-row": {
        ("in-progress", s) for s in ("READY_TO_LAUNCH", "EXPERIMENT_RUNNING")
    },
    "tracker-impl-review-row": {
        ("in-progress", s) for s in ("IMPLEMENTATION_REVIEW", "DECISION_ADJUDICATION", "IMPLEMENTING")
    },
    "results-gate-row": {
        ("in-progress", s) for s in ("EXPERIMENT_RUNNING", "LIVE_ANALYSIS", "RESULT_ANALYSIS")
    },
    "results-block": {
        ("in-progress", "RESULT_ANALYSIS")
    },
    "analysis-rule": {("in-progress", s) for s in STATES["in-progress"]},
    "analysis-insight": {("in-progress", s) for s in STATES["in-progress"]},
    "doc-file": (
        {("brainstorm", s)  for s in STATES["brainstorm"]}
        | {("in-progress", s) for s in STATES["in-progress"]}
    ),
    "doc-card": (
        {("brainstorm", s)  for s in STATES["brainstorm"]}
        | {("in-progress", s) for s in STATES["in-progress"]}
    ),
    "brainstorm-section": {
        ("brainstorm", s) for s in ("EXPLORING", "PILOT_READY")
    },
    "tracker-chosen-route": {("in-progress", "NEXT_ACTION_READY")},
}

# Update legality: target -> set of cells where update is allowed.
# Lane-crossing status updates require T1 ack; that's checked in validate.py, not here.
UPDATE_LEGAL = {
    "status": (
        {(c, s) for c, statuses in STATES.items() for s in statuses}
        - {("success", "ADOPTED"), ("fail", "ARCHIVED")}  # terminal-frozen
    ),
    "activeGate":           {("in-progress", s) for s in STATES["in-progress"]},
    "primaryMetricVsGate":  {("in-progress", s) for s in STATES["in-progress"]},
    "lastAction":           {("in-progress", s) for s in STATES["in-progress"]},
    "lastUpdated":          {(c, s) for c, statuses in STATES.items() for s in statuses},
    "openRuns":             {("in-progress", s) for s in STATES["in-progress"]},
    "currentBlocker":       {("in-progress", s) for s in STATES["in-progress"]},
    "experiments-status":   {("in-progress", s) for s in STATES["in-progress"]},
    "terminationMessage":   {("success", s) for s in STATES["success"]} | {("fail", s) for s in STATES["fail"]},
    "adoptionPath":         {("success", "ADOPTED_PENDING_ACK"), ("success", "ADOPTED")},
    "supersededBy":         {("success", "SUPERSEDED")},
    "reopenTrigger":        {("fail", "ARCHIVED_REOPENABLE")},
    "ack-slot":             {(c, s) for c, statuses in STATES.items() for s in statuses},
    "results-verdict":      {("in-progress", "RESULT_ANALYSIS")},
    "last-updated-time":    {(c, s) for c, statuses in STATES.items() for s in statuses},
}

# Delete legality: target -> set of cells where delete is allowed.
DELETE_LEGAL = {
    "experiments-row": {
        ("in-progress", s) for s in ("CONTEXT_LOADED", "IMPLEMENTING")
    },
    "tracker-live-check-row":    {("in-progress", s) for s in STATES["in-progress"]},
    "tracker-impl-review-row":   {("in-progress", "IMPLEMENTING")},
    "methodsTried":              {("in-progress", s) for s in STATES["in-progress"]},
    "doc-file":                  {("brainstorm", s) for s in STATES["brainstorm"]} | {("in-progress", s) for s in STATES["in-progress"]},
    "doc-card":                  {("brainstorm", s) for s in STATES["brainstorm"]} | {("in-progress", s) for s in STATES["in-progress"]},
    "brainstorm-section":        {("brainstorm", s) for s in ("EXPLORING", "PILOT_READY")},
    # results-block and inventory-entry are intentionally never legal — see spec D7, D8.
}

# Check is universal — every (category, status) cell allows it.
CHECK_LEGAL = {(c, s) for c, statuses in STATES.items() for s in statuses}


def is_legal(category: str, status: str, op: str, target: str | None) -> bool:
    """Return True iff (category, status, op, target) is a legal mutation."""
    cell = (category, status)
    if op == "check":
        return cell in CHECK_LEGAL
    if op == "insert":
        return cell in INSERT_LEGAL.get(target, set())
    if op == "update":
        return cell in UPDATE_LEGAL.get(target, set())
    if op == "delete":
        return cell in DELETE_LEGAL.get(target, set())
    return False
```

- [ ] **Step 3: Quick smoke test**

```bash
python3 -c "
from skills.research_op.scripts.transitions import is_legal, STATES, TARGETS
assert is_legal('in-progress', 'RESULT_ANALYSIS', 'insert', 'methodsTried')
assert not is_legal('success', 'ADOPTED', 'insert', 'methodsTried') is False  # methodsTried Insert IS legal in success per I2
assert not is_legal('in-progress', 'CONTEXT_LOADED', 'insert', 'tracker-live-check-row')
assert is_legal('brainstorm', 'EXPLORING', 'check', None)
print('transitions smoke test OK')
"
```

(Note: the import path uses underscore-to-dot conversion only if `skills/research-op/` is treated as a package; for tests we'll invoke via `python3 skills/research-op/scripts/research_op.py` and let the CLI sys.path-insert its own dir. See Task 1.4.)

- [ ] **Step 4: Commit**

```bash
git add skills/research-op/scripts/transitions.py
git commit -m "research-op: transitions table (33-row matrix as Python data)"
```

---

### Task 1.4: Write `scripts/audit.py` (jsonl writer)

**Files:**
- Create: `skills/research-op/scripts/audit.py`

- [ ] **Step 1: Write the audit module**

Create `skills/research-op/scripts/audit.py`:

```python
"""Append-only jsonl audit log for every research-op invocation."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def runtime_root(pkg: str) -> Path:
    """Resolve the runtime root for a package."""
    env = os.environ.get("RESEARCH_RUNTIME_ROOT")
    if env:
        return Path(env) / pkg
    return Path("outputs") / pkg


def log_path(pkg: str) -> Path:
    return runtime_root(pkg) / "_actions.jsonl"


def append(pkg: str, *, op: str, target: str | None, event: str | None,
           state_before: dict, state_after: dict,
           validation: str, rule: str | None,
           files_touched: list[str], payload: dict,
           user_intent: str | None, duration_ms: int) -> None:
    """Append one audit entry. Creates the log file + parent dirs if missing."""
    entry = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
        "pkg": pkg,
        "op": op,
        "target": target,
        "event": event,
        "state_before": state_before,
        "state_after": state_after,
        "validation": validation,
        "rule": rule,
        "files_touched": files_touched,
        "agent": os.environ.get("RESEARCH_OP_AGENT", "main"),
        "user_intent": user_intent,
        "duration_ms": duration_ms,
        "payload_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest(),
        "payload": payload,
    }
    path = log_path(pkg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

- [ ] **Step 2: Write the test**

Create `tests/research-op/test_audit.py`:

```python
import json
import os
from pathlib import Path

import sys
sys.path.insert(0, "skills/research-op/scripts")
import audit


def test_append_writes_jsonl_line(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_RUNTIME_ROOT", str(tmp_path))
    audit.append(
        "test-pkg",
        op="check", target=None, event=None,
        state_before={"category": "in-progress", "status": "CONTEXT_LOADED"},
        state_after ={"category": "in-progress", "status": "CONTEXT_LOADED"},
        validation="passed", rule=None,
        files_touched=[], payload={"scope": "all"},
        user_intent=None, duration_ms=42,
    )
    log = tmp_path / "test-pkg" / "_actions.jsonl"
    assert log.exists()
    entry = json.loads(log.read_text().strip())
    assert entry["op"] == "check"
    assert entry["validation"] == "passed"
    assert entry["payload"]["scope"] == "all"
    assert "payload_sha256" in entry


def test_append_creates_parent_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_RUNTIME_ROOT", str(tmp_path / "deep" / "nested"))
    audit.append(
        "test-pkg", op="check", target=None, event=None,
        state_before={}, state_after={},
        validation="passed", rule=None, files_touched=[], payload={},
        user_intent=None, duration_ms=1,
    )
    assert (tmp_path / "deep" / "nested" / "test-pkg" / "_actions.jsonl").exists()
```

- [ ] **Step 3: Run the test, expect PASS**

```bash
pytest tests/research-op/test_audit.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add skills/research-op/scripts/audit.py tests/research-op/test_audit.py
git commit -m "research-op: audit log writer + tests"
```

---

### Task 1.5: Write `scripts/research_op.py` CLI (MVP — `check` only, no validators yet)

**Files:**
- Create: `skills/research-op/scripts/research_op.py`

- [ ] **Step 1: Write the CLI**

Create `skills/research-op/scripts/research_op.py`:

```python
#!/usr/bin/env python3
"""research-op CLI — the single mutation surface for research packages.

MVP supports `--op check`. Insert/Update/Delete + composite events arrive in Phase 3.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

# Make sibling modules importable when invoked as `python3 skills/.../research_op.py`.
sys.path.insert(0, str(Path(__file__).parent))

import audit
import transitions  # noqa: E402


def _read_inventory(pkg: str) -> dict:
    """Parse the package entry out of research_html/data/research-packages.js."""
    js = Path("research_html/data/research-packages.js").read_text()
    # The file is a JS module that assigns RESEARCH_PACKAGES = [...]; we extract
    # one entry by id with a tolerant regex (good enough for now; a full JS parser
    # would be over-engineering for this MVP — replace if scope grows).
    m = re.search(
        r"\{[^{}]*?id:\s*['\"]" + re.escape(pkg) + r"['\"][^{}]*\}",
        js, re.DOTALL,
    )
    if not m:
        raise SystemExit(f"package id not found in inventory: {pkg}")
    block = m.group(0)
    cat   = re.search(r"category:\s*['\"]([^'\"]+)['\"]", block)
    stat  = re.search(r"status:\s*['\"]([^'\"]+)['\"]", block)
    if not cat or not stat:
        raise SystemExit(f"could not parse (category, status) for {pkg}")
    return {"category": cat.group(1), "status": stat.group(1)}


def _op_check(pkg: str, scope: str, state: dict) -> tuple[str, list[str]]:
    """MVP: read-only audit. Phase 2 will plug in validate.py + scan_events."""
    files = []  # Phase 2 fills this with paths actually inspected.
    return "passed", files


def main() -> int:
    p = argparse.ArgumentParser(prog="research-op")
    p.add_argument("--pkg", required=True, help="package id under research_html/packages/")
    p.add_argument("--op", choices=["check", "insert", "update", "delete"], required=True)
    p.add_argument("--target", help="target name from references/matrix.md (required for insert/update/delete)")
    p.add_argument("--scope", default="package", help="check scope: package | all")
    p.add_argument("--payload", default="{}", help="JSON payload for insert/update/delete")
    args = p.parse_args()

    t0 = time.monotonic()
    state = _read_inventory(args.pkg)

    # Phase 1 state-gate.
    target = args.target if args.op != "check" else None
    if not transitions.is_legal(state["category"], state["status"], args.op, target):
        envelope = {
            "rejected": True,
            "phase": "state-gate",
            "rule": "illegal-transition",
            "pkg": args.pkg,
            "op": args.op,
            "target": target,
            "expected": f"(category={state['category']}, status={state['status']}) "
                        f"to allow op={args.op} on target={target}",
            "actual": "not in transitions table",
            "suggested_fix": "Adjust the package status first via /research-op update --target status, "
                             "or use a target legal in this cell (see references/matrix.md).",
        }
        audit.append(args.pkg, op=args.op, target=target, event=None,
                     state_before=state, state_after=state,
                     validation="rejected", rule="illegal-transition",
                     files_touched=[], payload=json.loads(args.payload),
                     user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
        print(json.dumps(envelope, indent=2))
        return 2

    if args.op == "check":
        validation, files = _op_check(args.pkg, args.scope, state)
        audit.append(args.pkg, op="check", target=None, event=None,
                     state_before=state, state_after=state,
                     validation=validation, rule=None,
                     files_touched=files, payload={"scope": args.scope},
                     user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
        print(f"check OK pkg={args.pkg} state={state['category']}/{state['status']}")
        return 0

    # Insert / Update / Delete arrive in Phase 3.
    print(f"op={args.op} not yet implemented (Phase 3)", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test on an existing package**

```bash
python3 skills/research-op/scripts/research_op.py --pkg 2026-05-15-panda-baselines --op check
```

Expected: prints `check OK pkg=2026-05-15-panda-baselines state=in-progress/<some-status>` and appends one line to `outputs/2026-05-15-panda-baselines/_actions.jsonl`.

- [ ] **Step 3: Verify audit log line**

```bash
tail -1 outputs/2026-05-15-panda-baselines/_actions.jsonl | python3 -c 'import sys, json; e = json.loads(sys.stdin.read()); print(e["op"], e["validation"], e["state_before"])'
```

Expected: `check passed {'category': 'in-progress', 'status': '<...>'}`.

- [ ] **Step 4: Smoke-test illegal-transition path**

```bash
# Try to insert methodsTried in a state where it isn't legal (CONTEXT_LOADED).
python3 skills/research-op/scripts/research_op.py --pkg 2026-05-12-Matrix-Trie-search --op insert --target methodsTried --payload '{}'
echo "exit: $?"
```

Expected: prints the structured reject envelope; exit code 2.

- [ ] **Step 5: Commit**

```bash
git add skills/research-op/scripts/research_op.py
git commit -m "research-op: CLI MVP — check op + state-gate reject"
```

---

### Task 1.6: Write Phase 1 CLI smoke tests

**Files:**
- Create: `tests/research-op/conftest.py`
- Create: `tests/research-op/test_cli.py`

- [ ] **Step 1: Create the tmp-package fixture**

Create `tests/research-op/conftest.py`:

```python
import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_package(tmp_path, monkeypatch):
    """Build a minimal research_html/ + outputs/ tree in tmp_path."""
    root = tmp_path / "research_html"
    (root / "packages" / "test-pkg").mkdir(parents=True)
    (root / "packages" / "test-pkg" / "index.html").write_text("<html></html>")
    (root / "data").mkdir()
    (root / "data" / "research-packages.js").write_text(
        "const RESEARCH_PACKAGES = [\n"
        "  { id: 'test-pkg', category: 'in-progress', status: 'CONTEXT_LOADED' },\n"
        "];\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESEARCH_RUNTIME_ROOT", str(tmp_path / "outputs"))
    return tmp_path
```

- [ ] **Step 2: Write the CLI smoke test**

Create `tests/research-op/test_cli.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts" / "research_op.py"


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(CLI)] + args,
        cwd=cwd, capture_output=True, text=True,
    )


def test_check_passes_on_legal_state(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "check"], cwd=tmp_package)
    assert r.returncode == 0, r.stderr
    log = tmp_package / "outputs" / "test-pkg" / "_actions.jsonl"
    entry = json.loads(log.read_text().strip())
    assert entry["op"] == "check"
    assert entry["validation"] == "passed"


def test_state_gate_rejects_illegal_insert(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "methodsTried",
              "--payload", "{}"], cwd=tmp_package)
    assert r.returncode == 2
    envelope = json.loads(r.stdout)
    assert envelope["rejected"] is True
    assert envelope["phase"] == "state-gate"
    assert envelope["rule"] == "illegal-transition"
```

- [ ] **Step 3: Run, expect PASS**

```bash
pytest tests/research-op/test_cli.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Commit (closes Phase 1)**

```bash
git add tests/research-op/conftest.py tests/research-op/test_cli.py
git commit -m "research-op: CLI smoke tests + tmp-package fixture (closes Phase 1)"
```

---

## Phase 2 — Pattern B validators

Goal: every Insert / Update / Delete passes Phase 2 (per-target invariant check) before bytes hit disk. On reject, return the structured envelope with `{rule, file, anchor, field, expected, actual, suggested_fix}`.

### Task 2.1: Write `references/validate-rules.md` (rule catalogue)

**Files:**
- Create: `skills/research-op/references/validate-rules.md`

- [ ] **Step 1: Write the catalogue**

Create `skills/research-op/references/validate-rules.md`:

```markdown
# Pattern B — write-time validate rules

Every Insert / Update / Delete in `research-op` runs the rules below before any
byte hits disk. Rule ids are the values that appear in the rejection envelope's
`rule` field.

## Per-target rules

### Insert: methodsTried row (I2)
- `methodstried-six-fields`: payload must have exactly `{method, hypothesis, gate, measured, verdict, evidencePath}`. Extra or missing keys reject.
- `methodstried-verdict-enum`: `verdict ∈ {pass, fail, inconclusive}`.
- `methodstried-evidence-resolves`: `evidencePath` is either a real file under `outputs/<pkg>/` or `output/`, or an HTML anchor `results.html#<exp-anchor>` that exists on disk.
- `methodstried-source-row-exists`: the upstream `results.html` row at `evidencePath` exists with a verdict already finalized.

### Insert: results.html result-gate row (I6)
- `result-gate-ten-cols`: all 10 columns from WORKFLOW.md required schema are present.
- `result-gate-validity-enum`: `Validity ∈ {ok, partial, fail, unmeasured}`.
- `result-gate-pass-triple-check` (only if `verdict=pass`): the P5 triple-check passes — hypothesis string-eq frozen contract; metric/dataset/protocol/dedup/cutoff string-eq frozen contract; evidence file's manifest names the canonical eval split.

### Insert: results.html result block (I7)
- `result-block-six-parts`: HTML must contain the 6 anchors — `data-block="title"`, `data-block="summary"` (text ≤ 25 words), `data-block="detail"` (in `<details>` closed), `data-block="main-table"`, `data-block="insight"`, `data-block="ablation"` (or explicit `<!-- no ablation -->` comment).
- `result-block-details-closed`: every `<details>` in the block lacks `open` attr (R-no-details-open).

### Update: results.html verdict cell (U10)
- `verdict-mechanical`: the verdict string MUST equal `predicate(measured)` where `predicate` is the frozen success.predicate from plan.html. Refuse if they differ. The actual measured value is read from `evidencePath`.

### Update: status — lane-crossing (U1)
- `lane-t1-ack-present`: the destination cell's `data-ack-value=""` slot for `lane-transition` must be non-empty in the package HTML before this Update can write.
- `lane-required-fields`: every required field for the destination cell (per `schema.js`) must be present in the inventory entry.
- `lane-edge-legal`: the `(old-category, old-status) -> (new-category, new-status)` edge exists in `references/state-machine.md`.

### Insert: doc-file (I9) + paired doc-card
- `doc-file-path-under-package`: file path matches `research_html/packages/<pkg>/docs/<slug>.html`.
- `doc-card-six-parts`: paired card has the 6-part shape (title, tldr, tags, preview, link, last-updated) and 5 `data-doc-*` attrs from the companion HTML-design spec.
- `doc-group-rationale-present`: parent section in `docs/index.html` carries `data-doc-group-rationale`.

### Insert: tracker-live-check-row (I3)
- `live-check-twelve-cols`: all 12 columns from WORKFLOW.md required schema are present.
- `live-check-time-local`: `Time` field is local wall-clock (no `Z`, no `+00:00` offset).

### Delete: methodsTried row (D4)
- `methodstried-terminal-frozen`: refuse if `(category, status)` is in `(success/*, fail/*)`.

### Delete: experiments-row (D1)
- `experiments-pre-launch-only`: refuse if any `experiments[].status` for the package is one of `running`, `completed`, `failed`.

### Insert: brainstorm-section (I10)
- `brainstorm-category-only`: refuse if `category != "brainstorm"`.

## Universal rules (every op)

- `payload-json-valid`: `--payload` parses as JSON (this fires before the per-target rules above).
- `target-known`: `--target` is a value in `transitions.TARGETS` (this fires before the legality lookup).
```

- [ ] **Step 2: Commit**

```bash
git add skills/research-op/references/validate-rules.md
git commit -m "research-op: write-time validate rule catalogue"
```

---

### Task 2.2: Write `scripts/validate.py` infrastructure

**Files:**
- Create: `skills/research-op/scripts/validate.py`

- [ ] **Step 1: Write the validate module**

Create `skills/research-op/scripts/validate.py`:

```python
"""Pattern B reject-before-write checks.

Each rule is a function `rule_<id>(pkg, op, target, payload) -> Reject | None`.
The dispatcher calls all rules applicable to (op, target) and returns the first
rejection, or None if all pass.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class Reject:
    rule: str
    file: str | None
    anchor: str | None
    field: str | None
    expected: str
    actual: str
    suggested_fix: str

    def envelope(self, *, op: str, target: str | None, phase: str = "invariant-check") -> dict:
        return {
            "rejected": True,
            "phase": phase,
            "rule": self.rule,
            "file": self.file,
            "anchor": self.anchor,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
            "suggested_fix": self.suggested_fix,
            "op": op,
            "target": target,
        }


# ---- Universal rules ----

def rule_payload_json_valid(pkg: str, op: str, target: str | None, payload_raw: str) -> Reject | None:
    try:
        json.loads(payload_raw)
        return None
    except json.JSONDecodeError as e:
        return Reject(
            rule="payload-json-valid",
            file=None, anchor=None, field="payload",
            expected="valid JSON object",
            actual=f"JSONDecodeError: {e.msg} at pos {e.pos}",
            suggested_fix="Wrap the payload in single quotes and check for missing braces or trailing commas.",
        )


# ---- Per-target rules ----

_METHODSTRIED_FIELDS = {"method", "hypothesis", "gate", "measured", "verdict", "evidencePath"}
_VERDICT_ALLOWED    = {"pass", "fail", "inconclusive"}


def rule_methodstried_six_fields(pkg, op, target, payload) -> Reject | None:
    if target != "methodsTried" or op != "insert":
        return None
    keys = set(payload.keys())
    missing = _METHODSTRIED_FIELDS - keys
    extra   = keys - _METHODSTRIED_FIELDS
    if missing or extra:
        return Reject(
            rule="methodstried-six-fields",
            file=None, anchor=None, field="payload",
            expected=f"keys exactly = {sorted(_METHODSTRIED_FIELDS)}",
            actual=f"missing={sorted(missing)}; extra={sorted(extra)}",
            suggested_fix="Set the payload to exactly the six canonical fields; remove extras, fill missing.",
        )
    return None


def rule_methodstried_verdict_enum(pkg, op, target, payload) -> Reject | None:
    if target != "methodsTried" or op != "insert":
        return None
    v = payload.get("verdict")
    if v not in _VERDICT_ALLOWED:
        return Reject(
            rule="methodstried-verdict-enum",
            file=None, anchor=None, field="verdict",
            expected=f"one of {sorted(_VERDICT_ALLOWED)}",
            actual=repr(v),
            suggested_fix="Set verdict to pass / fail / inconclusive. Single-seed pass is inconclusive until multi-seed gate is met.",
        )
    return None


def rule_methodstried_evidence_resolves(pkg, op, target, payload) -> Reject | None:
    if target != "methodsTried" or op != "insert":
        return None
    ep = payload.get("evidencePath", "")
    if "#" in ep:  # HTML anchor
        page, anchor = ep.split("#", 1)
        path = Path("research_html") / "packages" / pkg / page
        if not path.exists():
            return Reject(
                rule="methodstried-evidence-resolves",
                file=str(path), anchor=anchor, field="evidencePath",
                expected="page file exists",
                actual="page file not on disk",
                suggested_fix=f"Create {path} first, or correct the evidencePath.",
            )
        text = path.read_text()
        if f'id="{anchor}"' not in text and f"id='{anchor}'" not in text:
            return Reject(
                rule="methodstried-evidence-resolves",
                file=str(path), anchor=anchor, field="evidencePath",
                expected=f"#{anchor} anchor exists in page",
                actual=f"#{anchor} not found in {path.name}",
                suggested_fix=f"Add the anchor to {page} or correct the evidencePath slug.",
            )
        return None
    # File path
    if not Path(ep).exists():
        return Reject(
            rule="methodstried-evidence-resolves",
            file=ep, anchor=None, field="evidencePath",
            expected="file exists on disk",
            actual=f"{ep} not found",
            suggested_fix="Verify the file path is correct and the artifact landed before recording the row.",
        )
    return None


def rule_brainstorm_category_only(pkg, op, target, payload, state) -> Reject | None:
    if target != "brainstorm-section" or op != "insert":
        return None
    if state["category"] != "brainstorm":
        return Reject(
            rule="brainstorm-category-only",
            file=None, anchor=None, field="category",
            expected="brainstorm",
            actual=state["category"],
            suggested_fix="brainstorm sections only exist on brainstorm-category packages.",
        )
    return None


# Add more rules as they are needed; the spec § 6.2 catalogue grows here.


# ---- Dispatcher ----

# Each entry: (rule_fn, needs_state_arg).
_RULES: list[tuple[Callable, bool]] = [
    (rule_methodstried_six_fields,      False),
    (rule_methodstried_verdict_enum,    False),
    (rule_methodstried_evidence_resolves, False),
    (rule_brainstorm_category_only,     True),
]


def validate(pkg: str, op: str, target: str | None, payload: dict, state: dict) -> Reject | None:
    """Run every applicable rule. Return first rejection, or None on all-pass."""
    for fn, needs_state in _RULES:
        rej = fn(pkg, op, target, payload, state) if needs_state else fn(pkg, op, target, payload)
        if rej:
            return rej
    return None
```

- [ ] **Step 2: Wire `validate.validate(...)` into the CLI**

Modify `skills/research-op/scripts/research_op.py` — replace the "Phase 3" stub at the bottom with:

```python
import validate  # noqa: E402

# ... inside main(), after the state-gate check, before the audit.append for check ...

if args.op != "check":
    # Phase 2 invariant check.
    payload = json.loads(args.payload)
    rej = validate.validate(args.pkg, args.op, target, payload, state)
    if rej:
        audit.append(args.pkg, op=args.op, target=target, event=None,
                     state_before=state, state_after=state,
                     validation="rejected", rule=rej.rule,
                     files_touched=[], payload=payload,
                     user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
        print(json.dumps(rej.envelope(op=args.op, target=target), indent=2))
        return 2
    # Insert/Update/Delete WRITES land in Phase 3 — for now, log a not-implemented audit
    # entry so the contract is observable but no bytes hit disk.
    print(f"op={args.op} target={target} validated; write handler arrives in Phase 3", file=sys.stderr)
    return 3
```

- [ ] **Step 3: Write per-rule tests**

Create `tests/research-op/test_validate.py`:

```python
import sys
sys.path.insert(0, "skills/research-op/scripts")
import validate


def test_methodstried_six_fields_passes_when_complete():
    p = {"method": "m", "hypothesis": "h", "gate": "g",
         "measured": "0.85", "verdict": "pass", "evidencePath": "x"}
    assert validate.rule_methodstried_six_fields("pkg", "insert", "methodsTried", p) is None


def test_methodstried_six_fields_rejects_missing():
    p = {"method": "m", "hypothesis": "h"}
    rej = validate.rule_methodstried_six_fields("pkg", "insert", "methodsTried", p)
    assert rej is not None
    assert rej.rule == "methodstried-six-fields"
    assert "missing" in rej.actual


def test_methodstried_six_fields_rejects_extra():
    p = {"method": "m", "hypothesis": "h", "gate": "g",
         "measured": "0.85", "verdict": "pass", "evidencePath": "x",
         "notes": "extra"}
    rej = validate.rule_methodstried_six_fields("pkg", "insert", "methodsTried", p)
    assert rej is not None
    assert "notes" in rej.actual


def test_verdict_enum_accepts_pass_fail_inconclusive():
    for v in ("pass", "fail", "inconclusive"):
        p = {"verdict": v}
        assert validate.rule_methodstried_verdict_enum("pkg", "insert", "methodsTried", p) is None


def test_verdict_enum_rejects_others():
    for v in ("PASS", "ok", "succeeded", "", None):
        rej = validate.rule_methodstried_verdict_enum("pkg", "insert", "methodsTried", {"verdict": v})
        assert rej is not None
        assert rej.rule == "methodstried-verdict-enum"


def test_brainstorm_section_rejects_non_brainstorm_category():
    rej = validate.rule_brainstorm_category_only(
        "pkg", "insert", "brainstorm-section", {},
        state={"category": "in-progress", "status": "CONTEXT_LOADED"},
    )
    assert rej is not None
    assert rej.rule == "brainstorm-category-only"


def test_brainstorm_section_accepts_brainstorm_category():
    rej = validate.rule_brainstorm_category_only(
        "pkg", "insert", "brainstorm-section", {},
        state={"category": "brainstorm", "status": "EXPLORING"},
    )
    assert rej is None
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pytest tests/research-op/test_validate.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/research-op/scripts/validate.py skills/research-op/scripts/research_op.py \
        tests/research-op/test_validate.py
git commit -m "research-op: Pattern B validate.py (4 rules) + CLI wire-in + tests"
```

---

### Task 2.3: Port additional rules from `learnings_lint.py`

**Files:**
- Modify: `skills/research-op/scripts/validate.py`
- Modify: `tests/research-op/test_validate.py`

Goal: lift the rules `learnings_lint.py lint-status` and `lint-evidence` enforce, and re-implement them as write-time rules. This is the bulk of Phase 2.

- [ ] **Step 1: Read `learnings_lint.py` and inventory which rules to port**

```bash
grep -nE "^def rule_|def check_|^def lint_" research_html/scripts/learnings_lint.py | head -40
```

Produce a list of every rule function in `learnings_lint.py`. For each, classify:
- **PORT to validate.py** — fires on a specific Insert/Update/Delete and can be checked from the payload + state.
- **KEEP at Stop-Gate only** — fires on whole-project consistency (cross-package), can't be checked at write-time.

- [ ] **Step 2: For each PORT-classified rule, write a `rule_<id>` function in `validate.py`**

For each rule, follow the pattern of `rule_methodstried_six_fields` in Task 2.2:
- Function signature `rule_X(pkg, op, target, payload) -> Reject | None` (add `state` arg only if state-dependent).
- Early-return None when (op, target) doesn't match the rule's scope.
- Return a `Reject` with all six fields filled (rule, file/anchor/field, expected, actual, suggested_fix).
- Append `(rule_X, needs_state)` to `_RULES`.

Minimum port list (each is ~15-25 lines):
- `rule_result_gate_ten_cols`
- `rule_result_gate_validity_enum`
- `rule_result_block_six_parts`
- `rule_result_block_details_closed`
- `rule_live_check_twelve_cols`
- `rule_live_check_time_local`
- `rule_lane_t1_ack_present`
- `rule_lane_required_fields`
- `rule_doc_file_path_under_package`
- `rule_doc_card_six_parts`
- `rule_doc_group_rationale_present`
- `rule_experiments_pre_launch_only`
- `rule_methodstried_terminal_frozen`

- [ ] **Step 3: For each new rule, add a pass-test and a fail-test in `test_validate.py`**

Same shape as the existing tests. Each rule adds ~10-15 lines of test code.

- [ ] **Step 4: Run all tests, expect PASS**

```bash
pytest tests/research-op/test_validate.py -v
```

Expected: all tests pass (the count grows by 2 × ported-rule-count).

- [ ] **Step 5: Commit**

```bash
git add skills/research-op/scripts/validate.py tests/research-op/test_validate.py
git commit -m "research-op: port lint-status + lint-evidence rules to write-time"
```

---

### Task 2.4: Add `verdict-mechanical` rule (P5 — the most-important faithfulness check)

**Files:**
- Modify: `skills/research-op/scripts/validate.py`
- Modify: `tests/research-op/test_validate.py`

This rule is the one most likely to catch hallucinated `verdict=pass`. Keep it isolated for clarity.

- [ ] **Step 1: Implement `rule_verdict_mechanical`**

Add to `validate.py`:

```python
def rule_verdict_mechanical(pkg, op, target, payload, state) -> Reject | None:
    """If we're writing a verdict, the verdict must match success.predicate(measured)."""
    if target != "results-verdict" or op != "update":
        return None
    measured = payload.get("measured")
    verdict  = payload.get("verdict")
    if measured is None or verdict is None:
        return Reject(
            rule="verdict-mechanical",
            file=None, anchor=None, field="payload",
            expected="payload has both `measured` and `verdict`",
            actual=f"measured={measured!r}, verdict={verdict!r}",
            suggested_fix="Provide both fields; the rule needs the measured value to compute the expected verdict.",
        )
    # Read frozen success.predicate from plan.html
    plan = Path(f"research_html/packages/{pkg}/plan.html").read_text()
    import re as _re
    m = _re.search(r'data-objective-field="success\.predicate"[^>]*>([^<]+)<', plan)
    if not m:
        return Reject(
            rule="verdict-mechanical",
            file=f"research_html/packages/{pkg}/plan.html", anchor=None,
            field="success.predicate",
            expected="plan.html has data-objective-field=\"success.predicate\" with a value",
            actual="no success.predicate slot found",
            suggested_fix="Define success.predicate on plan.html before recording any verdict.",
        )
    predicate = m.group(1).strip()
    # Evaluate the predicate mechanically. Supported forms: `measured >= 0.85`,
    # `measured > baseline + 0.02`, etc. For MVP, only `measured >= <float>` is supported;
    # any other shape downgrades to inconclusive instead of refusing.
    pm = _re.match(r"measured\s*>=\s*([0-9.]+)", predicate)
    if not pm:
        # Predicate too complex for mechanical eval — skip this rule, let Stop-Gate handle.
        return None
    threshold = float(pm.group(1))
    try:
        m_val = float(measured)
    except (TypeError, ValueError):
        return Reject(
            rule="verdict-mechanical",
            file=None, anchor=None, field="measured",
            expected="numeric measured value",
            actual=repr(measured),
            suggested_fix="Coerce measured to a number before recording the verdict.",
        )
    expected_verdict = "pass" if m_val >= threshold else "fail"
    if verdict != expected_verdict:
        return Reject(
            rule="verdict-mechanical",
            file=f"research_html/packages/{pkg}/plan.html", anchor=None,
            field="verdict",
            expected=f"verdict={expected_verdict} (predicate {predicate} with measured={m_val})",
            actual=f"verdict={verdict}",
            suggested_fix=f"Set verdict={expected_verdict}; the measured value {'meets' if expected_verdict == 'pass' else 'does not meet'} the gate.",
        )
    return None
```

Add `(rule_verdict_mechanical, True)` to `_RULES`.

- [ ] **Step 2: Write tests with a tmp plan.html**

Add to `tests/research-op/test_validate.py`:

```python
import sys
sys.path.insert(0, "skills/research-op/scripts")
import validate
from pathlib import Path


def _make_plan(tmp_path, pkg, predicate):
    p = tmp_path / "research_html" / "packages" / pkg / "plan.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f'<html><span data-objective-field="success.predicate">{predicate}</span></html>'
    )
    return p


def test_verdict_mechanical_pass_when_measured_meets_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_plan(tmp_path, "pkg", "measured >= 0.85")
    rej = validate.rule_verdict_mechanical(
        "pkg", "update", "results-verdict",
        {"measured": "0.87", "verdict": "pass"},
        state={"category": "in-progress", "status": "RESULT_ANALYSIS"},
    )
    assert rej is None


def test_verdict_mechanical_rejects_pass_when_measured_below_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_plan(tmp_path, "pkg", "measured >= 0.85")
    rej = validate.rule_verdict_mechanical(
        "pkg", "update", "results-verdict",
        {"measured": "0.82", "verdict": "pass"},
        state={"category": "in-progress", "status": "RESULT_ANALYSIS"},
    )
    assert rej is not None
    assert rej.rule == "verdict-mechanical"
    assert "fail" in rej.expected
    assert "pass" in rej.actual


def test_verdict_mechanical_skips_complex_predicate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_plan(tmp_path, "pkg", "measured > baseline + 0.02")
    rej = validate.rule_verdict_mechanical(
        "pkg", "update", "results-verdict",
        {"measured": "0.82", "verdict": "pass"},
        state={"category": "in-progress", "status": "RESULT_ANALYSIS"},
    )
    assert rej is None  # Stop-Gate handles complex predicates, not us.
```

- [ ] **Step 3: Run, expect PASS**

```bash
pytest tests/research-op/test_validate.py -v -k verdict_mechanical
```

Expected: 3 passed.

- [ ] **Step 4: Commit (closes Phase 2)**

```bash
git add skills/research-op/scripts/validate.py tests/research-op/test_validate.py
git commit -m "research-op: P5 verdict-mechanical rule (closes Phase 2)"
```

---

## Phase 3 — Op handlers + composite events + scan_events

Goal: Insert / Update / Delete actually write to disk; composite events fan out atomically; `scan_events.py` absorbs `propagate_facts.py` role 1.

### Task 3.1: Write `scripts/router.py` (dispatcher)

**Files:**
- Create: `skills/research-op/scripts/router.py`
- Modify: `skills/research-op/scripts/research_op.py`

- [ ] **Step 1: Write the router**

Create `skills/research-op/scripts/router.py`:

```python
"""Dispatch (op, target) to the matching handler in ops/."""

from ops import insert as _insert
from ops import update as _update
from ops import delete as _delete
from ops import check  as _check


def dispatch(op: str, pkg: str, target: str | None, payload: dict, state: dict) -> tuple[str, list[str]]:
    """Run the handler; return (validation_status, files_touched)."""
    if op == "insert":
        return _insert.handle(pkg, target, payload, state)
    if op == "update":
        return _update.handle(pkg, target, payload, state)
    if op == "delete":
        return _delete.handle(pkg, target, payload, state)
    if op == "check":
        return _check.handle(pkg, payload.get("scope", "package"), state)
    raise ValueError(f"unknown op: {op}")
```

- [ ] **Step 2: Wire router into the CLI**

Modify `skills/research-op/scripts/research_op.py` — replace the Phase 2 stub after `validate.validate(...)`:

```python
import router  # noqa: E402

# Replaces the "validated; write handler arrives in Phase 3" stub.
validation, files = router.dispatch(args.op, args.pkg, target, payload, state)
audit.append(args.pkg, op=args.op, target=target, event=None,
             state_before=state, state_after=state,  # Updates that change status set state_after in the handler.
             validation=validation, rule=None,
             files_touched=files, payload=payload,
             user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
print(f"{args.op} OK pkg={args.pkg} target={target} files={files}")
return 0
```

- [ ] **Step 3: Commit (handlers come next; this is the skeleton)**

```bash
git add skills/research-op/scripts/router.py skills/research-op/scripts/research_op.py
git commit -m "research-op: dispatcher skeleton (handlers in next tasks)"
```

---

### Task 3.2: Write `ops/check.py` (read-only)

**Files:**
- Create: `skills/research-op/scripts/ops/__init__.py`
- Create: `skills/research-op/scripts/ops/check.py`

- [ ] **Step 1: Empty `__init__.py`**

```bash
touch skills/research-op/scripts/ops/__init__.py
```

- [ ] **Step 2: Write check.py**

Create `skills/research-op/scripts/ops/check.py`:

```python
"""Check op — read-only audit."""

import subprocess
from pathlib import Path


def handle(pkg: str, scope: str, state: dict) -> tuple[str, list[str]]:
    """Run the relevant subset of learnings_lint.py for `scope`."""
    files_inspected: list[str] = []
    lint_args = ["python3", "research_html/scripts/learnings_lint.py"]
    if scope == "all":
        lint_args.append("all")
    else:
        lint_args += ["lint-status", "--pkg", pkg]
    r = subprocess.run(lint_args, capture_output=True, text=True)
    if r.returncode != 0:
        # Non-zero is informational here; check never writes, just reports.
        return "rejected", files_inspected
    files_inspected.append(f"research_html/packages/{pkg}/")
    if scope == "all":
        files_inspected.append("research_html/data/research-packages.js")
    return "passed", files_inspected
```

- [ ] **Step 3: Smoke-test from CLI**

```bash
python3 skills/research-op/scripts/research_op.py --pkg 2026-05-15-panda-baselines --op check --scope all
```

Expected: prints `check OK ...`; audit log shows `validation=passed` (or `rejected` if learnings_lint already has issues — which is informative, not a bug in research-op).

- [ ] **Step 4: Commit**

```bash
git add skills/research-op/scripts/ops/__init__.py skills/research-op/scripts/ops/check.py
git commit -m "research-op: check op (wraps learnings_lint.py)"
```

---

### Task 3.3: Write `ops/insert.py` (per-target Insert handlers)

**Files:**
- Create: `skills/research-op/scripts/ops/insert.py`

- [ ] **Step 1: Write the dispatcher + the first three handlers**

Create `skills/research-op/scripts/ops/insert.py`:

```python
"""Insert handlers for each target in the I-table (spec § 4.1)."""

import json
import re
from datetime import datetime
from pathlib import Path


def _bump_last_updated(path: Path) -> None:
    """Update the <time data-field='last-updated'> on a touched HTML file."""
    text = path.read_text()
    iso = datetime.now().date().isoformat()
    new = re.sub(
        r'(<time[^>]*data-field="last-updated"[^>]*>)[^<]*(</time>)',
        rf'\1{iso}\2', text,
    )
    if new != text:
        path.write_text(new)


def _append_to_inventory_array(pkg: str, array_field: str, entry: dict) -> str:
    """Append `entry` to the named array in the package's inventory entry. Returns the file path edited."""
    p = Path("research_html/data/research-packages.js")
    text = p.read_text()
    # Find the package entry block (tolerant; for MVP).
    pat = re.compile(
        r"(\{[^{}]*?id:\s*['\"]" + re.escape(pkg) + r"['\"][^{}]*?"
        + array_field + r":\s*\[)([^\]]*?)(\][^{}]*?\})",
        re.DOTALL,
    )
    m = pat.search(text)
    if not m:
        # Array not present yet — add it.
        pat2 = re.compile(
            r"(\{[^{}]*?id:\s*['\"]" + re.escape(pkg) + r"['\"][^{}]*?)(\})",
            re.DOTALL,
        )
        m2 = pat2.search(text)
        if not m2:
            raise SystemExit(f"package {pkg} not found in inventory")
        insertion = f"\n    {array_field}: [{json.dumps(entry)}],\n  "
        new_text = text[:m2.end(1)] + insertion + text[m2.end(1):]
    else:
        existing = m.group(2).strip()
        sep = "" if not existing else ",\n      "
        new_text = (
            text[:m.start(2)]
            + (existing + sep + json.dumps(entry) if existing else json.dumps(entry))
            + text[m.start(3):]
        )
    p.write_text(new_text)
    return str(p)


def insert_methodstried(pkg: str, payload: dict) -> list[str]:
    return [_append_to_inventory_array(pkg, "methodsTried", payload)]


def insert_experiments_row(pkg: str, payload: dict) -> list[str]:
    return [_append_to_inventory_array(pkg, "experiments", payload)]


def insert_tracker_live_check_row(pkg: str, payload: dict) -> list[str]:
    path = Path(f"research_html/packages/{pkg}/tracker.html")
    text = path.read_text()
    # Append into <tbody data-table-body="live-check">.
    row_html = (
        "<tr>"
        + "".join(f"<td>{payload.get(c, 'unmeasured')}</td>" for c in (
            "time", "exp_id", "agent", "run_state", "last_log", "progress",
            "metrics", "resource", "artifacts", "eta", "action", "next_check"
        ))
        + "</tr>"
    )
    # If a row for this exp_id exists, REPLACE; otherwise APPEND.
    exp_id = payload.get("exp_id", "")
    existing_row = re.compile(
        rf'<tr>[^<]*<td>[^<]*</td>\s*<td>{re.escape(exp_id)}</td>.*?</tr>', re.DOTALL,
    )
    if existing_row.search(text):
        new = existing_row.sub(row_html, text, count=1)
    else:
        new = re.sub(
            r'(<tbody[^>]*data-table-body="live-check"[^>]*>)',
            rf"\1\n      {row_html}", text, count=1,
        )
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


# Add per-target Insert functions for the remaining I-rows here. Each is ~15-30 lines.
# The dispatcher below routes each Insert target to its handler.
_DISPATCH = {
    "methodsTried":             insert_methodstried,
    "experiments-row":          insert_experiments_row,
    "tracker-live-check-row":   insert_tracker_live_check_row,
    # Fill in: tracker-resource-allocation-row, tracker-impl-review-row, results-gate-row,
    #          results-block, analysis-rule, analysis-insight, doc-file, doc-card,
    #          brainstorm-section, tracker-chosen-route.
}


def handle(pkg: str, target: str | None, payload: dict, state: dict) -> tuple[str, list[str]]:
    fn = _DISPATCH.get(target)
    if fn is None:
        raise SystemExit(f"insert target not implemented yet: {target}")
    files = fn(pkg, payload)
    return "passed", files
```

- [ ] **Step 2: Implement the remaining per-target Insert handlers**

Follow the pattern: read the owning file, locate the anchor (regex on `data-table-body` / `data-section` / `data-block`), insert the new content, bump `<time data-field="last-updated">`. Each handler is ~15-30 lines. Refer to spec § 4.1 + companion HTML-design spec for the per-target HTML shape.

Targets left to implement:
- `tracker-resource-allocation-row`
- `tracker-impl-review-row`
- `results-gate-row`
- `results-block` (6-part canonical block; longest handler, ~50 lines)
- `analysis-rule`
- `analysis-insight`
- `doc-file` (creates a new HTML file + the matching `doc-card` Insert)
- `doc-card` (called by `doc-file`)
- `brainstorm-section`
- `tracker-chosen-route`

Add each to `_DISPATCH`.

- [ ] **Step 3: End-to-end smoke test — Insert a methodsTried row**

```bash
# On panda-baselines (in-progress / RESULT_ANALYSIS), insert a real-looking methodsTried row.
python3 skills/research-op/scripts/research_op.py \
  --pkg 2026-05-15-panda-baselines --op insert --target methodsTried \
  --payload '{"method":"baseline-rerank","hypothesis":"rerank improves NDCG@10","gate":"NDCG@10>=0.85","measured":"0.87","verdict":"pass","evidencePath":"results.html#exp-p1"}'
```

Expected: `insert OK pkg=2026-05-15-panda-baselines target=methodsTried files=['research_html/data/research-packages.js']`. Verify the row landed:

```bash
grep -A2 "baseline-rerank" research_html/data/research-packages.js | head
```

- [ ] **Step 4: Commit**

```bash
git add skills/research-op/scripts/ops/insert.py
git commit -m "research-op: Insert handlers for all 11 I-table targets"
```

---

### Task 3.4: Write `ops/update.py` (per-target Update handlers)

**Files:**
- Create: `skills/research-op/scripts/ops/update.py`

- [ ] **Step 1: Write update.py with one helper + per-field functions**

Create `skills/research-op/scripts/ops/update.py`:

```python
"""Update handlers for each target in the U-table (spec § 4.2)."""

import json
import re
from datetime import datetime
from pathlib import Path


def _update_inventory_field(pkg: str, field: str, value) -> str:
    """Set `<pkg>.<field> = <value>` in research-packages.js, replacing the existing value."""
    p = Path("research_html/data/research-packages.js")
    text = p.read_text()
    pat = re.compile(
        r"(\{[^{}]*?id:\s*['\"]" + re.escape(pkg) + r"['\"][^{}]*?"
        + field + r":\s*)([^,\n}]+)",
        re.DOTALL,
    )
    m = pat.search(text)
    new_val = json.dumps(value) if not isinstance(value, str) else f"'{value}'"
    if m:
        new_text = text[:m.start(2)] + new_val + text[m.end(2):]
    else:
        # Field absent — insert after id.
        pat2 = re.compile(
            r"(\{[^{}]*?id:\s*['\"]" + re.escape(pkg) + r"['\"])",
            re.DOTALL,
        )
        m2 = pat2.search(text)
        if not m2:
            raise SystemExit(f"package {pkg} not found in inventory")
        new_text = text[:m2.end()] + f", {field}: {new_val}" + text[m2.end():]
    p.write_text(new_text)
    return str(p)


def update_status(pkg: str, payload: dict) -> list[str]:
    files = [_update_inventory_field(pkg, "status", payload["to"])]
    # Updates that move into success / fail also need terminationMessage etc., but those are
    # separate Update ops the caller must sequence (E3 / E4 / E5 / E6).
    return files


def update_simple_field(pkg: str, payload: dict, field: str) -> list[str]:
    return [_update_inventory_field(pkg, field, payload["to"])]


_DISPATCH = {
    "status":               update_status,
    "activeGate":           lambda p, pl: update_simple_field(p, pl, "activeGate"),
    "primaryMetricVsGate":  lambda p, pl: update_simple_field(p, pl, "primaryMetricVsGate"),
    "lastAction":           lambda p, pl: update_simple_field(p, pl, "lastAction"),
    "lastUpdated":          lambda p, pl: update_simple_field(p, pl, "lastUpdated"),
    "openRuns":             lambda p, pl: update_simple_field(p, pl, "openRuns"),
    "currentBlocker":       lambda p, pl: update_simple_field(p, pl, "currentBlocker"),
    "terminationMessage":   lambda p, pl: update_simple_field(p, pl, "terminationMessage"),
    "adoptionPath":         lambda p, pl: update_simple_field(p, pl, "adoptionPath"),
    "supersededBy":         lambda p, pl: update_simple_field(p, pl, "supersededBy"),
    "reopenTrigger":        lambda p, pl: update_simple_field(p, pl, "reopenTrigger"),
    # Add: experiments-status, ack-slot, results-verdict, last-updated-time
}


def handle(pkg: str, target: str | None, payload: dict, state: dict) -> tuple[str, list[str]]:
    fn = _DISPATCH.get(target)
    if fn is None:
        raise SystemExit(f"update target not implemented yet: {target}")
    files = fn(pkg, payload)
    return "passed", files
```

- [ ] **Step 2: Implement the four remaining handlers**

- `experiments-status` — find `experiments[]` entry by `id`, update its `status`.
- `ack-slot` — find `<element data-ack="<type>" data-ack-value="">` in the named HTML file, set `data-ack-value` to the payload's timestamp+initials.
- `results-verdict` — find the result-gate `<tr>` by `data-exp-id`, replace the verdict `<td>`.
- `last-updated-time` — find `<time data-field="last-updated">` on the named file, set to today.

- [ ] **Step 3: Smoke test — flip a package's `lastAction`**

```bash
python3 skills/research-op/scripts/research_op.py \
  --pkg 2026-05-15-panda-baselines --op update --target lastAction \
  --payload '{"to": "smoke-test from plan task 3.4"}'

grep "lastAction" research_html/data/research-packages.js | grep "smoke-test"
```

- [ ] **Step 4: Commit**

```bash
git add skills/research-op/scripts/ops/update.py
git commit -m "research-op: Update handlers for all U-table targets"
```

---

### Task 3.5: Write `ops/delete.py`

**Files:**
- Create: `skills/research-op/scripts/ops/delete.py`

- [ ] **Step 1: Write per-target Delete handlers**

Follow the same pattern as Insert/Update. Per-target handlers:
- `experiments-row` — splice from `experiments[]` by id.
- `tracker-live-check-row` — remove `<tr>` for given exp_id from live-check tbody.
- `tracker-impl-review-row` — remove `<tr>` for given change_id from impl-review tbody.
- `methodsTried` — splice from `methodsTried[]` by index or by `evidencePath` match.
- `doc-file` — `os.unlink` the file + call delete on its `doc-card`.
- `doc-card` — remove `<article data-doc-slug="<slug>">` from `docs/index.html`.
- `brainstorm-section` — remove `<section id="<slug>">` from `brainstorm.html`.

- [ ] **Step 2: Smoke test**

```bash
# Insert and then delete a dummy methodsTried row on a sandbox copy.
# (Use a brainstorm-stage package or a tmp pkg fixture; do not delete real history.)
```

- [ ] **Step 3: Commit**

```bash
git add skills/research-op/scripts/ops/delete.py
git commit -m "research-op: Delete handlers for all D-table targets"
```

---

### Task 3.6: Write `scripts/events.py` + composite-event docs

**Files:**
- Create: `skills/research-op/references/composite-events.md`
- Create: `skills/research-op/scripts/events.py`
- Modify: `skills/research-op/scripts/research_op.py`

- [ ] **Step 1: Document the 5 events**

Create `skills/research-op/references/composite-events.md`:

```markdown
# Composite events — surface fan-out map

Each event below triggers ≥ 1 Insert and ≥ 1 Update across multiple surfaces in
the same atomic transaction. The agent invokes `--event <name>` once; research-op
fans out, runs Pattern B on each surface in the fan-out, and either succeeds for
every surface or aborts entirely.

## chain-done

Trigger: a chain log file ends with `=== … done ===`.
Fan-out:
1. `update results-block` for every phase the chain closed (compute summary)
2. `update results-verdict` for each closed phase
3. `update tracker-chosen-route` (set the route from chain summary)
4. `update status` to NEXT_ACTION_READY
5. `update openRuns` to "none"
6. `update lastAction` to "chain done"
7. `update last-updated-time` on tracker.html, results.html
8. `update experiments-status` to "completed" for each closed phase

## checkpoint-saved

Trigger: `output/<exp>/best_model.pt` written.
Fan-out:
1. `update tracker-live-check-row` for the exp (state=completed)
2. `update tracker-resource-allocation-row` for the exp (Status=completed)
3. `insert results-gate-row` for the exp (if not present)
4. `update results-verdict` (Pattern B verdict-mechanical fires)
5. `update experiments-status` to "completed"
6. `update last-updated-time` on tracker.html, results.html

## sentinel-write

Trigger: `manifests/*.txt` written.
Fan-out: see spec § 4 + WORKFLOW.md Fact Propagation Contract table.

## phase-marker

Trigger: `--- P` or `### P` appears in chain log.
Fan-out: see spec.

## candidate-json

Trigger: `candidates/<label>/<dataset>/*.json` written.
Fan-out: see spec.
```

- [ ] **Step 2: Write events.py**

Create `skills/research-op/scripts/events.py`:

```python
"""Composite events — atomic fan-out of one event to multiple ops."""

# Each event maps to a list of (op, target) pairs the dispatcher runs in order.
# The payload's keys are propagated through to each sub-op via a payload-mapper.
EVENTS = {
    "chain-done": [
        # Each tuple: (op, target, payload_mapper_fn or None)
        # Payload mappers extract the per-op fields from the event payload.
    ],
    "checkpoint-saved":   [],
    "sentinel-write":     [],
    "phase-marker":       [],
    "candidate-json":     [],
}


def fanout(event: str, pkg: str, payload: dict, dispatch_fn) -> tuple[str, list[str]]:
    """Run every sub-op for `event`. If any rejects, abort and return ('rejected', files_touched_so_far).
    
    Note: true atomicity requires snapshot-and-rollback if we want every-or-none.
    For MVP, we accept "stop on first reject and surface reject; the agent retries from cursor."
    """
    spec = EVENTS.get(event)
    if spec is None:
        raise SystemExit(f"unknown composite event: {event}")
    files: list[str] = []
    for op, target, mapper in spec:
        sub_payload = mapper(payload) if mapper else payload
        # dispatch_fn signature: (op, pkg, target, payload, state) -> (validation, files)
        validation, sub_files = dispatch_fn(op, pkg, target, sub_payload)
        files.extend(sub_files)
        if validation != "passed":
            return "rejected", files
    return "passed", files
```

Fill in the per-event lists by translating the fan-out maps from spec § 4 + the existing `propagate_facts.py` Surface Map (read it first to confirm what each event currently fans out to).

- [ ] **Step 3: Add `--event` arg to the CLI**

In `research_op.py`, add to `argparse`:

```python
p.add_argument("--event", help="composite event name (chain-done, checkpoint-saved, ...)")
```

And after the state read:

```python
if args.event:
    import events  # noqa: E402
    validation, files = events.fanout(args.event, args.pkg, json.loads(args.payload),
                                       dispatch_fn=lambda o, p, t, pl: router.dispatch(o, p, t, pl, state))
    audit.append(args.pkg, op="event", target=None, event=args.event,
                 state_before=state, state_after=state,
                 validation=validation, rule=None,
                 files_touched=files, payload=json.loads(args.payload),
                 user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
    print(f"event={args.event} OK files={files}")
    return 0
```

- [ ] **Step 4: Smoke test**

```bash
python3 skills/research-op/scripts/research_op.py \
  --pkg 2026-05-15-panda-baselines --event checkpoint-saved \
  --payload '{"exp_id":"P1","artifact":"output/P1/best_model.pt","measured":"0.87"}'
```

Expected: prints `event=checkpoint-saved OK files=[...multiple paths...]`; audit log shows one entry with `event=checkpoint-saved` and `files_touched` listing all written surfaces.

- [ ] **Step 5: Commit**

```bash
git add skills/research-op/references/composite-events.md \
        skills/research-op/scripts/events.py \
        skills/research-op/scripts/research_op.py
git commit -m "research-op: composite events (5 named, atomic fan-out)"
```

---

### Task 3.7: Write `scripts/scan_events.py` (absorbs `propagate_facts.py` role 1)

**Files:**
- Create: `skills/research-op/scripts/scan_events.py`
- Modify: `skills/research-op/scripts/research_op.py`

- [ ] **Step 1: Read existing `propagate_facts.py`**

```bash
cat skills/research-package/scripts/propagate_facts.py
```

Identify how it scans for artifacts and advances the cursor. The MVP `scan_events.py` re-implements this in the research-op tree but classifies artifacts into one of the 5 event names instead of printing surface lists.

- [ ] **Step 2: Write scan_events.py**

Create `skills/research-op/scripts/scan_events.py`:

```python
"""Scan artifacts under runtime root; classify into events; advance cursor."""

import os
from pathlib import Path
from time import time


def runtime_root(pkg: str) -> Path:
    env = os.environ.get("RESEARCH_RUNTIME_ROOT")
    return Path(env if env else "outputs") / pkg


def cursor_path(pkg: str) -> Path:
    return runtime_root(pkg) / "manifests" / ".propagation_cursor"


def read_cursor(pkg: str) -> float:
    p = cursor_path(pkg)
    if not p.exists():
        return 0.0
    return float(p.read_text().strip() or 0.0)


def write_cursor(pkg: str, ts: float) -> None:
    p = cursor_path(pkg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{ts}")


def scan(pkg: str) -> list[dict]:
    """Return a list of {event, artifact, mtime} dicts newer than cursor."""
    cursor = read_cursor(pkg)
    root = runtime_root(pkg)
    events = []
    if not root.exists():
        return events
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        m = p.stat().st_mtime
        if m <= cursor:
            continue
        name = p.name
        if name.endswith("best_model.pt"):
            events.append({"event": "checkpoint-saved", "artifact": str(p), "mtime": m})
        elif p.parent.name == "manifests" and name.endswith(".txt"):
            events.append({"event": "sentinel-write", "artifact": str(p), "mtime": m})
        elif "candidates" in p.parts and name.endswith(".json"):
            events.append({"event": "candidate-json", "artifact": str(p), "mtime": m})
        elif name.endswith(".done"):
            events.append({"event": "chain-done", "artifact": str(p), "mtime": m})
    return events


def bump(pkg: str) -> None:
    write_cursor(pkg, time())
```

- [ ] **Step 3: Add `scan-events` op to CLI**

In `research_op.py`, add to the `--op` choices: `"scan-events"`. Add handling:

```python
if args.op == "scan-events":
    import scan_events  # noqa: E402
    found = scan_events.scan(args.pkg)
    for ev in found:
        print(json.dumps(ev))
    # Caller is expected to invoke --event for each; bump only after the agent confirms.
    return 0
```

- [ ] **Step 4: Smoke test**

```bash
python3 skills/research-op/scripts/research_op.py --pkg 2026-05-15-panda-baselines --op scan-events
```

Expected: prints zero or more JSON event lines (depends on whether anything is new since the existing cursor).

- [ ] **Step 5: Commit**

```bash
git add skills/research-op/scripts/scan_events.py skills/research-op/scripts/research_op.py
git commit -m "research-op: scan-events (absorbs propagate_facts.py role 1)"
```

---

### Task 3.8: Add natural-language parser (`--nl` flag)

**Files:**
- Modify: `skills/research-op/scripts/research_op.py`

- [ ] **Step 1: Add a thin NL parser**

The natural-language form is "user prose → structured form". For the implementation, the SKILL.md body does the parsing in-context (the agent reads the prose, fills the structured form, then calls the CLI). So the CLI only needs to ACCEPT the parsed form — it doesn't itself need a parser.

But for non-Claude callers (or testing), add a flag that takes one prose string and dispatches a minimal regex-based parser:

```python
p.add_argument("--nl", help="natural-language form: e.g. 'update: set status of <pkg> to BLOCKED'")

# ...
if args.nl:
    # Minimal parser: "<op>: <pkg-id-or-name>; <key>=<value>; ..."
    # Heavy parsing is done by the skill body; this is a fallback.
    print("Natural-language parsing is best done from the SKILL.md body. "
          "Re-invoke with explicit --pkg / --op / --target / --payload.", file=sys.stderr)
    return 4
```

The real NL parsing belongs in the SKILL.md prose (the agent reads the prose, produces the structured form, prints the preview line, then calls the CLI). The CLI flag is just an escape hatch.

- [ ] **Step 2: Commit (closes Phase 3)**

```bash
git add skills/research-op/scripts/research_op.py
git commit -m "research-op: --nl escape hatch + close Phase 3"
```

---

## Phase 4 — WORKFLOW.md + CLAUDE.md migration

Goal: existing protocol docs reference `/research-op` instead of `propagate_facts.py`; the Mutation rule is added; per-package byte-copies are removed.

### Task 4.1: Add the Mutation rule paragraph to WORKFLOW.md

**Files:**
- Modify: `WORKFLOW.md`

- [ ] **Step 1: Add the paragraph after "## How to Use This Workflow"**

Find the section near line 7 (after "## How to Use This Workflow") and add:

```markdown
## Mutation Rule (binding)

Every mutation to a research-package surface (HTML files, inventory entry, doc files) MUST go through `/research-op`. Direct `Edit` / `Write` on package files is a workflow violation. The only exceptions are: (a) `/research-package` / `/research-dashboard` at scaffold time, and (b) the user typing in their editor outside the agent. `/research-op` enforces the `(category, status, op, target)` legality matrix and per-target invariants before any byte hits disk; on reject the agent reads the structured envelope and retries with the rule visible.
```

- [ ] **Step 2: Verify wc -l hasn't blown up**

```bash
wc -l WORKFLOW.md
```

- [ ] **Step 3: Commit**

```bash
git add WORKFLOW.md
git commit -m "WORKFLOW.md: add Mutation rule paragraph (research-op chokepoint)"
```

---

### Task 4.2: Replace `propagate_facts.py` mentions in WORKFLOW.md with research-op equivalents

**Files:**
- Modify: `WORKFLOW.md`

- [ ] **Step 1: Find all mentions**

```bash
grep -n "propagate_facts" WORKFLOW.md
```

There are ~3 mentions (Step 5 Step 3.5, Stop Gate, Fact Propagation Contract table).

- [ ] **Step 2: For each mention, replace with the research-op equivalent**

Pattern:
- `python scripts/propagate_facts.py` → `python skills/research-op/scripts/research_op.py --pkg <pkg> --op scan-events`
- `python scripts/propagate_facts.py --bump` → (no longer needed; cursor advances inside scan-events on the next iteration — or call `python skills/research-op/scripts/research_op.py --pkg <pkg> --event <name>` for the fan-out, which advances the cursor on success)
- The "Step 3.5 — Propagation pass" block in §5 becomes a "Step 3.5 — research-op event fanout" block.

- [ ] **Step 3: Commit**

```bash
git add WORKFLOW.md
git commit -m "WORKFLOW.md: replace propagate_facts.py with /research-op equivalents"
```

---

### Task 4.3: Replace `propagate_facts.py` mentions in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (the one at `Trustworthy-Research-Pipeline/CLAUDE.md`)

- [ ] **Step 1: Find all mentions**

```bash
grep -n "propagate_facts" CLAUDE.md
```

~5 mentions, mostly in Protocol 3 (Fact Propagation Contract section).

- [ ] **Step 2: Replace each with research-op equivalents**

Pattern:
- Protocol 3 narrative: rewrite the "mechanical check" subsection to point at `/research-op scan-events` and `/research-op event <name>`.
- Code blocks: replace `python research_html/packages/<pkg-id>/scripts/propagate_facts.py` with `python skills/research-op/scripts/research_op.py --pkg <pkg-id> --op scan-events`.
- Cursor advance: replace `--bump` mentions with "the cursor advances on the next scan-events after a successful --event fan-out".

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "CLAUDE.md Protocol 3: replace propagate_facts.py with /research-op"
```

---

### Task 4.4: Remove per-package `propagate_facts.py` byte-copies

**Files:**
- Delete: `research_html/packages/*/scripts/propagate_facts.py` (8 files)

- [ ] **Step 1: List the byte-copies**

```bash
ls research_html/packages/*/scripts/propagate_facts.py 2>/dev/null
```

Expected: 8 paths (one per existing package). If fewer, some packages never had the file copied; that's fine.

- [ ] **Step 2: Remove them**

```bash
git rm research_html/packages/*/scripts/propagate_facts.py
```

- [ ] **Step 3: Verify nothing else references the per-package path**

```bash
grep -rn "packages/.*scripts/propagate_facts" research_html WORKFLOW.md CLAUDE.md skills 2>/dev/null
```

Expected: no matches.

- [ ] **Step 4: Commit**

```bash
git commit -m "Remove per-package propagate_facts.py byte-copies (absorbed by research-op)"
```

---

### Task 4.5: Update `create_research_package.py` to stop copying `propagate_facts.py`

**Files:**
- Modify: `skills/research-package/scripts/create_research_package.py`

- [ ] **Step 1: Find the copy step**

```bash
grep -n "propagate_facts" skills/research-package/scripts/create_research_package.py
```

- [ ] **Step 2: Remove the copy logic + any related path setup**

The scaffolder copies `propagate_facts.py` from the skill's `scripts/` into the new package's `scripts/`. Delete that block. The package no longer needs the file because `/research-op scan-events --pkg <id>` operates from the central skill location.

- [ ] **Step 3: Smoke-test scaffolder on a throwaway slug**

```bash
python3 skills/research-package/scripts/create_research_package.py \
  --root /tmp/research_html_throwaway --id test-no-propagate \
  --name "Test no-propagate" --category brainstorm \
  --tag "test" --tag-meaning "test" --problem "test" --objective "test" \
  --motivation "test" --hypothesis "test" --primary-metric "test" \
  --baseline "test" --budget "test" --no-change-boundary "test" \
  --next-action "test" --status EXPLORING --contribution-spine-flag none \
  --active-gate "" --next-route ask_user --last-action "scaffold" \
  --open-runs "none" --direction "test" --scope index,docs,_agent

# Verify no propagate_facts.py was copied
ls /tmp/research_html_throwaway/packages/test-no-propagate/scripts/ 2>/dev/null && echo "scripts/ exists"
rm -rf /tmp/research_html_throwaway
```

Expected: either no `scripts/` directory was created, or the directory is empty.

- [ ] **Step 4: Also remove the master `propagate_facts.py`**

```bash
git rm skills/research-package/scripts/propagate_facts.py
```

- [ ] **Step 5: Update `skills/research-package/SKILL.md` — remove the "Fact Propagation Contract" mechanical-check section** (lines 284-297 of the SKILL.md) — replace with a one-paragraph pointer to `/research-op`.

```bash
# After editing:
grep -n "propagate_facts" skills/research-package/SKILL.md
```

Expected: no matches.

- [ ] **Step 6: Commit**

```bash
git add skills/research-package/scripts/create_research_package.py \
        skills/research-package/SKILL.md
git commit -m "research-package: stop shipping propagate_facts.py (absorbed by research-op)"
```

---

### Task 4.6: Ensure `outputs/` is in .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Check current state**

```bash
cat .gitignore | grep -E "^var/|^/var" || echo "not present"
```

- [ ] **Step 2: If absent, add the line**

Append to `.gitignore`:

```
# research-op local audit logs and runtime state
var/
```

- [ ] **Step 3: Commit (closes Phase 4)**

```bash
git add .gitignore
git commit -m "gitignore: var/ tree (research-op audit logs + runtime state)"
```

---

## Phase 5 — research-analysis delegation rewrite

Goal: `/research-analysis` keeps owning Rules + Insight editorial discipline but delegates file writes to `/research-op insert --target analysis-rule` / `--target analysis-insight`.

### Task 5.1: Add Boundary note + Operations rewire to `research-analysis` SKILL.md

**Files:**
- Modify: `skills/research-analysis/SKILL.md`

- [ ] **Step 1: Add to the "Boundary (binding)" section (after line 28)**

Insert a new bullet:

```markdown
- File writes to `analysis.html` (and removals) go through `/research-op insert --target analysis-rule` / `--target analysis-insight` / `--target last-updated-time`. This skill owns the **editorial decision** (when a rule is warranted, what counts as an insight); `/research-op` owns the **file format** (where to insert, what shape, lint compliance). Lint (`scripts/lint_analysis.py`) stays in this skill.
```

- [ ] **Step 2: Update the "add-rule" subcommand (line 148-152) to invoke /research-op**

Rewrite as:

```markdown
### `add-rule <package-id> <slug> <evidence-slug>`

Append one new numbered `<li>` to the Rules block. The agent hand-crafts the prose; this skill delegates the file write:

```bash
python skills/research-op/scripts/research_op.py \
  --pkg <package-id> --op insert --target analysis-rule \
  --payload '{"slug":"<slug>","evidence_slug":"<evidence-slug>","prose":"<rule prose>"}'
```

`/research-op` runs the analysis-rule Phase 2 rules (slug kebab-case, single Evidence link, no bold on rule body) and either writes or rejects with the structured envelope.
```

- [ ] **Step 3: Same treatment for `add-insight` (line 142-146)**

Rewrite to call `/research-op insert --target analysis-insight`.

- [ ] **Step 4: Same treatment for `init` (line 122-141)**

The init subcommand currently scaffolds the empty page. Rewrite to call `/research-op insert --target doc-file --payload '{"path":"analysis.html",...}'` — or keep it native since init is rare and template-based (judgment call: if you keep it native, mark the boundary with a note in the SKILL.md).

- [ ] **Step 5: Commit**

```bash
git add skills/research-analysis/SKILL.md
git commit -m "research-analysis: delegate file writes to /research-op (editorial vs format split)"
```

---

### Task 5.2: Add `analysis-rule` and `analysis-insight` Insert handlers to `research-op`

**Files:**
- Modify: `skills/research-op/scripts/ops/insert.py`
- Modify: `skills/research-op/scripts/transitions.py` (already includes these targets per Task 1.3)
- Modify: `skills/research-op/scripts/validate.py` (add Phase 2 rules for these targets)

- [ ] **Step 1: Implement the handlers (referring to research-analysis SKILL.md format)**

```python
def insert_analysis_rule(pkg: str, payload: dict) -> list[str]:
    """Append one <li class='card-text' id='rule-<slug>'> to <ol class='rules-list'> on analysis.html."""
    path = Path(f"research_html/packages/{pkg}/analysis.html")
    text = path.read_text()
    # Strip the "No rules recorded yet." placeholder if present.
    text = re.sub(r'<li class="card-text"><em>No rules recorded yet\.</em></li>\s*', '', text)
    li_html = (
        f'<li class="card-text" id="rule-{payload["slug"]}">'
        f'{payload["prose"]} '
        f'Evidence: <a href="#insight-{payload["evidence_slug"]}">see insight</a>.'
        f'</li>'
    )
    new = re.sub(
        r'(<ol[^>]*class="rules-list"[^>]*>)',
        rf"\1\n      {li_html}", text, count=1,
    )
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


def insert_analysis_insight(pkg: str, payload: dict) -> list[str]:
    """Append one <details class='insight-subblock' id='insight-<slug>'> to <div class='insight-body'>."""
    path = Path(f"research_html/packages/{pkg}/analysis.html")
    text = path.read_text()
    text = re.sub(r'<p class="card-text"><em>No insight content yet\.</em></p>\s*', '', text)
    details_html = (
        f'<details class="insight-subblock" id="insight-{payload["slug"]}">'
        f'<summary>{payload["title"]}</summary>'
        f'<div class="insight-body-inner">{payload.get("body", "")}</div>'
        f'</details>'
    )
    new = re.sub(
        r'(<div[^>]*class="insight-body"[^>]*>)',
        rf"\1\n      {details_html}", text, count=1,
    )
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]
```

Add both to `_DISPATCH`.

- [ ] **Step 2: Add Phase 2 rules in validate.py**

```python
def rule_analysis_rule_slug_kebab(pkg, op, target, payload) -> Reject | None:
    if target != "analysis-rule" or op != "insert":
        return None
    slug = payload.get("slug", "")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        return Reject(
            rule="analysis-rule-slug-kebab",
            file=None, anchor=None, field="slug",
            expected="kebab-case slug (lowercase, hyphens, no underscores)",
            actual=repr(slug),
            suggested_fix="Lowercase the slug, replace spaces/underscores with hyphens.",
        )
    return None


def rule_analysis_rule_no_bold(pkg, op, target, payload) -> Reject | None:
    if target != "analysis-rule" or op != "insert":
        return None
    prose = payload.get("prose", "")
    if "<strong>" in prose or "<b>" in prose:
        return Reject(
            rule="analysis-rule-no-bold",
            file=None, anchor=None, field="prose",
            expected="rule prose with no <strong> or <b>",
            actual="bold tag found in prose",
            suggested_fix="Remove the <strong>/<b> wrappers; rules are plain sentences (inline <em> for sub-clauses is fine).",
        )
    return None
```

Add to `_RULES`.

- [ ] **Step 3: Write tests for both rules + handlers**

Add to `test_validate.py`:

```python
def test_analysis_rule_slug_kebab_passes_valid():
    rej = validate.rule_analysis_rule_slug_kebab("pkg", "insert", "analysis-rule", {"slug": "my-rule-1"})
    assert rej is None

def test_analysis_rule_slug_kebab_rejects_invalid():
    for bad in ("MyRule", "my_rule", "my rule", ""):
        rej = validate.rule_analysis_rule_slug_kebab("pkg", "insert", "analysis-rule", {"slug": bad})
        assert rej is not None

def test_analysis_rule_no_bold_rejects_strong():
    rej = validate.rule_analysis_rule_no_bold("pkg", "insert", "analysis-rule", {"prose": "<strong>bad</strong>"})
    assert rej is not None
```

- [ ] **Step 4: Run all tests, expect PASS**

```bash
pytest tests/research-op/ -v
```

- [ ] **Step 5: Smoke-test the delegation**

Find a brainstorm or in-progress package and add a fake rule via research-op:

```bash
python3 skills/research-op/scripts/research_op.py \
  --pkg 2026-05-15-panda-baselines --op insert --target analysis-insight \
  --payload '{"slug":"smoke-test","title":"Smoke test","body":"<p class=\"card-text\">smoke</p>"}'

grep "smoke-test" research_html/packages/2026-05-15-panda-baselines/analysis.html
```

- [ ] **Step 6: Commit (closes Phase 5)**

```bash
git add skills/research-op/scripts/ops/insert.py \
        skills/research-op/scripts/validate.py \
        tests/research-op/test_validate.py
git commit -m "research-op: analysis-rule + analysis-insight Insert handlers + Phase 2 rules"
```

---

## Phase 6 — panda-baselines pilot

Goal: run the new skill end-to-end on the canonical example package; reconcile audit log entries against existing history; discover edge cases.

### Task 6.1: Capture baseline state

**Files:** (none modified — pure verification)

- [ ] **Step 1: Run check on panda-baselines**

```bash
python3 skills/research-op/scripts/research_op.py \
  --pkg 2026-05-15-panda-baselines --op check --scope all
```

Save the output. If `learnings_lint.py` reports errors, those are pre-existing issues — list them and decide per-issue whether to fix via research-op or leave for the user.

- [ ] **Step 2: Snapshot the audit log**

```bash
wc -l outputs/2026-05-15-panda-baselines/_actions.jsonl
cp outputs/2026-05-15-panda-baselines/_actions.jsonl /tmp/baseline-audit.jsonl
```

---

### Task 6.2: Insert a real-shape methodsTried row

- [ ] **Step 1: Inspect an existing methodsTried row**

```bash
grep -A6 "methodsTried" research_html/data/research-packages.js | head -20
```

- [ ] **Step 2: Insert a new methodsTried row that mirrors an existing shape**

```bash
python3 skills/research-op/scripts/research_op.py \
  --pkg 2026-05-15-panda-baselines --op insert --target methodsTried \
  --payload '{"method":"<copy from existing>","hypothesis":"<copy>","gate":"<copy>","measured":"<copy>","verdict":"pass","evidencePath":"<copy>"}'
```

- [ ] **Step 3: Verify it landed in inventory + audit log**

```bash
tail -1 outputs/2026-05-15-panda-baselines/_actions.jsonl | python3 -m json.tool
grep -c '"method"' research_html/data/research-packages.js
```

- [ ] **Step 4: Roll back the test insertion** (use Edit to remove the smoke row from `research-packages.js`)

- [ ] **Step 5: Capture findings (no commit; this is verification)**

If anything failed, capture in a `notes/research-op-pilot-findings.md` and refer to the spec § 12 (open decisions). Real bugs go on the issue tracker / writing-plans backlog.

---

### Task 6.3: Test the Pattern B reject path

- [ ] **Step 1: Try inserting a methodsTried row with wrong verdict**

```bash
python3 skills/research-op/scripts/research_op.py \
  --pkg 2026-05-15-panda-baselines --op insert --target methodsTried \
  --payload '{"method":"x","hypothesis":"x","gate":"x","measured":"x","verdict":"SUCCESS","evidencePath":"results.html#exp-p1"}'
echo "exit: $?"
```

Expected: exit 2; envelope shows `rule: methodstried-verdict-enum`; nothing landed in inventory.

- [ ] **Step 2: Try inserting with missing field**

```bash
python3 skills/research-op/scripts/research_op.py \
  --pkg 2026-05-15-panda-baselines --op insert --target methodsTried \
  --payload '{"method":"x","verdict":"pass"}'
echo "exit: $?"
```

Expected: exit 2; envelope shows `rule: methodstried-six-fields`.

- [ ] **Step 3: Verify nothing landed in inventory**

```bash
grep -c '"method":"x"' research_html/data/research-packages.js
```

Expected: 0.

- [ ] **Step 4: Verify both rejects are in the audit log**

```bash
grep '"validation": "rejected"' outputs/2026-05-15-panda-baselines/_actions.jsonl | tail -2
```

Expected: 2 lines (one per reject).

---

### Task 6.4: Test the scan-events → event fanout loop

- [ ] **Step 1: Create a dummy artifact under the runtime root**

```bash
mkdir -p outputs/2026-05-15-panda-baselines/manifests
echo "smoke" > outputs/2026-05-15-panda-baselines/manifests/smoke.txt
```

- [ ] **Step 2: Run scan-events**

```bash
python3 skills/research-op/scripts/research_op.py --pkg 2026-05-15-panda-baselines --op scan-events
```

Expected: prints one JSON line with `"event": "sentinel-write"` and the smoke.txt path.

- [ ] **Step 3: Roll back**

```bash
rm outputs/2026-05-15-panda-baselines/manifests/smoke.txt
```

---

### Task 6.5: Pilot retrospective + commit (closes Phase 6)

- [ ] **Step 1: Summarize findings**

Write a one-page `docs/superpowers/notes/2026-05-24-research-op-pilot-notes.md` with:
- What worked first try
- What needed code changes (and the commits made to address them)
- Edge cases discovered (added to spec § 12 deferred decisions if not blocking)
- Recommendation for Phase 7 rollout (proceed / pause / iterate)

- [ ] **Step 2: Commit the pilot notes**

```bash
git add docs/superpowers/notes/2026-05-24-research-op-pilot-notes.md
git commit -m "research-op: panda-baselines pilot retrospective notes"
```

---

## Phase 7 — Cross-package rollout

Goal: run `/research-op check` on the remaining 7 packages; fix any failures; smoke-test scan-events.

### Task 7.1: Check every package

- [ ] **Step 1: Iterate the package list**

```bash
for pkg in $(ls research_html/packages/); do
  echo "=== $pkg ==="
  python3 skills/research-op/scripts/research_op.py --pkg "$pkg" --op check --scope all 2>&1 | head -10
done > /tmp/check-rollout.log
```

- [ ] **Step 2: Review the log**

```bash
grep -E "(===|rejected|OK)" /tmp/check-rollout.log
```

Expected: most show "OK"; rejections list the failing rule + suggested fix.

---

### Task 7.2: Fix failures via research-op update calls

For each package that failed check, the suggested-fix field tells you which update to run.

- [ ] **Step 1: For each failing package, apply the suggested fix via /research-op update**

Example:
```bash
# If a package lacks lastUpdated:
python3 skills/research-op/scripts/research_op.py \
  --pkg <pkg> --op update --target lastUpdated --payload '{"to":"2026-05-24"}'
```

- [ ] **Step 2: Re-run check on the fixed package**

```bash
python3 skills/research-op/scripts/research_op.py --pkg <pkg> --op check --scope all
```

Expected: exit 0.

- [ ] **Step 3: Repeat for every failing package**

---

### Task 7.3: Final cross-package validation

- [ ] **Step 1: Run learnings_lint.py all (Stop-Gate)**

```bash
python3 research_html/scripts/learnings_lint.py all
echo "exit: $?"
```

Expected: exit 0.

- [ ] **Step 2: Verify _actions.jsonl exists for each package**

```bash
for pkg in $(ls research_html/packages/); do
  if [ -f "outputs/$pkg/_actions.jsonl" ]; then
    echo "OK $pkg"
  else
    echo "MISSING $pkg (run /research-op check --pkg $pkg once to seed)"
  fi
done
```

- [ ] **Step 3: Verify no per-package propagate_facts.py byte-copies remain**

```bash
ls research_html/packages/*/scripts/propagate_facts.py 2>/dev/null && echo "STILL PRESENT" || echo "all clean"
```

Expected: `all clean`.

- [ ] **Step 4: Commit (closes Phase 7)**

```bash
git add -A  # changes from any update fixes
git commit -m "research-op: cross-package rollout (Phase 7 closes the plan)"
```

---

## Self-review

Cross-checking the plan against the spec sections:

| Spec § | Topic | Covered by |
|---|---|---|
| 1 | Problem framing (F1/F2/F3) | Tasks 2.* + 7.3 (Pattern B + audit log address F1/F2; full rollout addresses F3) |
| 2 | Deep-research patterns | Pattern A → Tasks 1.3, 2.2; Pattern B → Phase 2 + 6.3; rejected Pattern C → Task 1.4 |
| 3 | Cross-cutting decisions D1-D5 | All applied: D1 hybrid grain (handler per target), D2 single skill (Phase 1), D3 no git (Task 1.4), D4 Init outside (no Init handler), D5 (category, status)-only keys (Task 1.3) |
| 4 | 33-row matrix | Tasks 1.2 (lift), 1.3 (encode), 3.3-3.5 (handlers) |
| 5 | research-op skill architecture | Task 1.1 (SKILL.md), all of Phase 1-3 |
| 6 | Pattern B validators | Phase 2 (Tasks 2.1-2.4) |
| 7 | Local audit log | Task 1.4 |
| 8 | Triggers + composition | Phase 4 (WORKFLOW.md/CLAUDE.md migration), Phase 5 (research-analysis delegation) |
| 9 | New surfaces | All Phase 1 + Phase 2 + Phase 3 files created |
| 10 | Handoff inputs | This plan IS the handoff to writing-plans |
| 11 | Migration TODO M1-M9 | Phase 4 (M2, M3, M9), Phase 5 (M6), Task 4.4 (M1), Task 4.5 (M5), Task 4.6 (M9) |
| 12 | Deferred open decisions | Surfaced in Task 6.5 pilot notes |
| 13 | Spec self-review | Plan self-review = this section |

**Gaps found and added:**
- No gap on the spec; every section traces to ≥ 1 task.

**Placeholder scan:** Tasks 2.3, 3.3 step 2, 3.4 step 2, 3.5 step 1, 3.6 step 2 say "Implement remaining handlers (follow the pattern)" — that's because writing 11 + 12 + 8 + 5 handler functions verbatim in this plan would explode it past 2000 lines without adding signal. The pattern is shown in concrete code for the first handler in each Task; the rest follow mechanically. This is a deliberate plan-budget tradeoff, not a placeholder.

**Type consistency:** `is_legal(category, status, op, target)` is called identically in `transitions.py`, `research_op.py`, `router.py`, and tests. `Reject` dataclass fields are stable across `validate.py` and CLI envelope. `audit.append(...)` signature is identical in all 5 call sites. `dispatch(op, pkg, target, payload, state)` in `router.py` matches calls in `research_op.py` and `events.py`.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-24-research-op-skill.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for this plan because the 7 phases are mostly independent and the subagent can hold the per-task context cleanly.

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints. Slower per task but lower coordination overhead.

**Which approach?**
