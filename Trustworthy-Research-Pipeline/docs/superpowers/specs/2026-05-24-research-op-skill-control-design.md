# Research-Op Skill Control — Design Spec

**Status:** draft — awaiting user review
**Date:** 2026-05-24
**Topic:** Agent-maintained research-package lifecycle via a single skill-controlled mutation surface
**Companion spec:** [`2026-05-24-trustworthy-pipeline-html-design.md`](2026-05-24-trustworthy-pipeline-html-design.md) — the 8-page HTML structure this design mutates

---

## 1. Problem framing

The companion spec locked the **structure** of a research package (8 stage pages + docs + inventory). This spec locks the **lifecycle control** — the agent must autonomously maintain N packages over multi-day runs and keep every package's format byte-identical to every other package's format, without per-package user instructions.

Three failure modes the current pipeline does not defend against:

**F1 — Cascading corruption from one bad write.**
The agent writes `verdict=pass` for a failed experiment (hallucination, value-vs-gate misread). `propagate_facts.py` fires chain-done → `methodsTried[]` appended → tracker Resume Block updated → headline strip flipped → Pending Actions card shifted. The Stop-Gate catches the original wrong verdict, but **five surfaces are now wrong** and the agent walks every one back.

**F2 — Silent stuck loops the user cannot see.**
The agent tries to insert a `methodsTried` row missing `evidencePath`. Lint catches it at the Stop-Gate. The agent retries with a guessed path. Lint catches it again. The user sees nothing — there is no live signal that the agent has been stuck for 3 turns on the same write. First visible failure is "we're 30 minutes behind schedule and nothing has landed."

**F3 — Format drift across packages.**
Each package is touched by the agent across many turns. Without a single chokepoint enforcing the per-page canon (the 8-page contracts from the companion spec), packages diverge — one package's results.html uses the 6-part canonical block, another invents a 4-part variant. The dashboard, learnings index, and cross-package navigation all break silently. End-of-turn lint catches schema violations but not "looks subtly different from spec."

**Goal:** make these three failure modes impossible to reach, without adding user touchpoints. The user invokes `/research-package` once per direction; from then on the agent maintains the package autonomously, with the same typed acks (P2) at terminal transitions and the same content invariants enforced before every write.

The user's nominated solution direction — "skill control" — was validated by the deep research (§3 below).

---

## 2. Deep-research summary (peer agent-framework patterns)

A subagent surveyed 10 frameworks for how they enforce file-format invariance and operation-state contracts in agent-maintained artifacts: Claude Code Skills (+ obra/superpowers), LangGraph, AutoGen / AG2, OpenHands, SWE-agent, Sakana AI Scientist v2, MetaGPT, Agent Laboratory, Aider, Cursor / Devin, OpenAI Swarm / Agents SDK.

Three patterns dominate and compose:

| Pattern | Source | What this spec adopts |
|---|---|---|
| **A — Conditional-edge transition table** | LangGraph (`add_conditional_edges` + state schema) | Encode legal `(category, status, op, target)` 4-tuples as a static Python dict; illegal combinations are unreachable by construction. The 18-cell `(category, status)` machine becomes a literal table in `scripts/transitions.py`. |
| **B — Reject-before-write with structured observation** | SWE-agent ACI (the paper's central reliability claim) | Move `learnings_lint.py` checks from Stop-Gate (post-turn) to write-time (pre-write). On reject, return `{rule, field, expected, actual, suggested-fix}`. No bytes hit disk. Agent retries with rule visible. Stop-Gate stays as defense-in-depth. |
| **C — Per-op git commit audit log** | Aider | **REJECTED.** The user opted out of git-tracking for per-package files. Replaced by a local append-only `var/research/<pkg>/_actions.jsonl`. |

Strong anti-pattern from the survey: do not store agent state in pickle blobs (Agent Laboratory's failure mode). Plain JSON / JS / HTML on disk is already correct in this project; this spec keeps it that way.

Composition recommendation from the survey: a **single shared mutator skill** with an internal Python router beats 5 per-op or 7 per-file skills (which all duplicate the state-gate and burn description budget). The obra/superpowers `using-superpowers` "must-check-first" meta-router discipline applied at the op layer.

---

## 3. Cross-cutting design decisions

The five locked decisions from the brainstorm:

| # | Decision | Why |
|---|---|---|
| **D1** | **Hybrid op grain.** Init = whole-package; Insert = row/card/section/new-file; Update = field (inventory-grained, painters re-render); Delete = row/section; Check = multi-grain read-only. | Matches the heterogeneous mutation patterns already in the codebase (M1.2 inventory writes + per-row HTML edits + new doc files). Forcing one uniform grain conflicts with how Init currently works (file scaffold) and with how Fact Propagation already works (multi-surface writes). |
| **D2** | **Single mutator skill `research-op`** + keep the 3 existing scaffolding skills. | Single transition table, single description budget, single place to fix the state machine. Existing scaffolders untouched — no migration risk to the just-finished 8-page redesign. Approach 2 (per-op skills) and Approach 3 (per-file skills) both fight the multi-file Fact Propagation Contract. |
| **D3** | **No git operations.** Per-op git commits explicitly rejected. Audit log is local jsonl. | User intent: package files are working files, not source-controlled artifacts; the agent should never run `git add` / `git commit` as part of any op. Files may still be in the dashboard repo (the user can commit when they choose), but the agent never invokes git. |
| **D4** | **Init stays outside the `research-op` matrix.** `research-op` only handles Insert / Update / Delete / Check on existing packages. | Init is rare and template-heavy; the existing `research-package` / `research-dashboard` skills already own it well. Duplicating that machinery in `research-op` would bloat without value. Symmetry break is acceptable. |
| **D5** | **Matrix keys on `(category, status)` only**, not on the compound `(category, status, workflow-state)`. | 18-cell table is readable and maintainable; ~120-cell compound table is not. Workflow-state is the *trigger* for an op, not the *gate*. Ops legal in a cell but meaningful only during a specific workflow-state have their precondition expressed in the validator, not the gate. |

---

## 4. The 5 operations × N states × file targets matrix

The matrix is **4 ops × 18 states × ~9 file slots** in principle, but compresses to ~33 rows because Check is universal and most Insert/Update/Delete rules group neatly by target.

### 4.1 Insert — add row / card / section / new file

| # | Target | Legal in `(category, status)` | Constraint / source |
|---|---|---|---|
| I1 | `experiments[]` row → paints plan.html + index.html | `(in-progress, CONTEXT_LOADED / IMPLEMENTING / READY_TO_LAUNCH)` | Pre-launch only; obeys 12-word `purpose` cap, atomic `gate` |
| I2 | `methodsTried[]` row → paints learnings.html | `(in-progress, RESULT_ANALYSIS / NEXT_ACTION_READY)` + during T1 ack window for `(success, *)` / `(fail, *)` | Source: results.html result-gate row with verdict + verified `evidencePath` (E1) |
| I3 | tracker live-check row | `(in-progress, EXPERIMENT_RUNNING / LIVE_ANALYSIS)` | One row per open exp; replaces prior row for same `exp_id` |
| I4 | tracker resource-allocation row | `(in-progress, READY_TO_LAUNCH → EXPERIMENT_RUNNING)` | One per planned exp |
| I5 | tracker impl-review row | `(in-progress, IMPLEMENTATION_REVIEW / DECISION_ADJUDICATION)` | One per `change_id` |
| I6 | results.html result-gate row | `(in-progress, EXPERIMENT_RUNNING → RESULT_ANALYSIS)` | One per planned experiment (P0, P1, …); not per measurement |
| I7 | results.html result block (6-part canon) | `(in-progress, RESULT_ANALYSIS)` | One per result group; obeys canonical 6-part shape |
| I8 | analysis.html rule / insight subblock | any `(in-progress, *)` after ≥ 1 finalized result-gate row | Owner skill: `research-analysis` (delegates writes to `research-op`) |
| I9 | `docs/<slug>.html` (new file) + paired doc card | any non-terminal cell | Group-design rule applies; card + file written atomically |
| I10 | brainstorm.html section | `(brainstorm, EXPLORING / PILOT_READY)` only | Forbidden in other categories |
| I11 | tracker chosen-route panel + considered-routes row | `(in-progress, NEXT_ACTION_READY)` | Per the companion spec (next-action folded into tracker) |

### 4.2 Update — mutate field (default path: inventory; HTML re-paints)

| # | Target | Legal in `(category, status)` | Ack type · source |
|---|---|---|---|
| U1 | `status` (lane-crossing) | All except terminal-frozen | **T1 `lane-transition`** ack required (E3) |
| U2 | `status` (intra-lane) | All `(in-progress, *)` transitions | No ack |
| U3 | `activeGate` / `primaryMetricVsGate` / `lastAction` / `lastUpdated` / `openRuns` / `currentBlocker` | `(in-progress, *)` | No ack (E2 in-progress update) |
| U4 | `experiments[i].status` (phase chip) | `(in-progress, *)` | No ack; driven by `scan-events` |
| U5 | `terminationMessage` | `(success, *)`, `(fail, *)` during T1 ack | **T1** (E3) |
| U6 | `adoptionPath` | `(success, ADOPTED_PENDING_ACK → ADOPTED)` | **T1 `codebase-merge`** (E4) |
| U7 | `supersededBy` | `(success, SUPERSEDED)` | **T1** (E5) |
| U8 | `reopenTrigger` | `(fail, ARCHIVED_REOPENABLE)` | **T1** (E6) |
| U9 | any `data-ack-value=""` slot (8 ack types per P2) | when the corresponding event arrives | **T1** of the slot's declared type |
| U10 | results.html verdict cell | `(in-progress, RESULT_ANALYSIS)` | Mechanically computed from `success.predicate` + verified value (P5); never overridden by prose |
| U11 | tracker Resume Block (painted from inventory) | any `(in-progress, *)` | No ack — painter re-derives from inventory |
| U12 | `<time data-field="last-updated">` on any HTML | any | Auto-bumped on every meaningful Insert/Update/Delete to that file |

### 4.3 Delete — remove row / card / section / file

| # | Target | Legal in `(category, status)` | Forbidden in |
|---|---|---|---|
| D1 | `experiments[]` row | `(in-progress, CONTEXT_LOADED / IMPLEMENTING)` only | After first phase launch — preserves audit |
| D2 | tracker live-check row | when run closes (one final row first, then optional cleanup post-archive) | While run is open |
| D3 | tracker impl-review row | `(in-progress, IMPLEMENTING)` only | After review started |
| D4 | `methodsTried[]` row | `(in-progress, *)` only, before E3 | **All of `(success, *)` and `(fail, *)`** (terminal freeze) |
| D5 | `docs/<slug>.html` file + paired doc card | any non-terminal cell | All of `(success, *)` and `(fail, *)` (preserve evidence) |
| D6 | brainstorm.html section | `(brainstorm, EXPLORING / PILOT_READY)` only | All other categories |
| D7 | results.html result block | **forbidden everywhere** — archive via lane move, not delete | All cells |
| D8 | inventory entry (whole package) | **forbidden via `research-op`** | All cells — archival is a lane move, not delete |

### 4.4 Check — read-only lint (universal)

| # | Scope | Legal in | Wraps |
|---|---|---|---|
| C1 | This-package state lint | All cells, always | `learnings_lint.py lint-status --pkg <id>` |
| C2 | This-package evidence resolution | All cells, always | `learnings_lint.py lint-evidence --pkg <id>` |
| C3 | This-package propagation pass (read-only) | All cells, always | `research-op scan-events --pkg <id> --dry-run` |
| C4 | Project-wide cross-package consistency | All cells, always | `learnings_lint.py all` |
| C5 | Schema gate for a proposed write (pre-condition for I* / U* / D*) | All cells, always | Pattern B reject-before-write hook |

### 4.5 Structural invariants the matrix encodes

1. **Terminal freeze** (`success/*` and `fail/*`): `methodsTried[]`, `terminationMessage`, `verdict`, `evidencePath` are Insert-once / Update-never-after-E3 / Delete-never. Rows D4 / D7 enforce this.
2. **Single-home rule** (M1.1): each Insert row has exactly one target file. Painters re-derive everywhere else. The matrix has no "Insert into A and also into B" cell.
3. **Per-event atomicity** (Fact Propagation Contract): a single artifact event (e.g., chain-done) triggers ≥ 1 Insert + ≥ 1 Update across multiple surfaces in the same turn. The matrix doesn't fight this — composite events (§ 5.2) become the single transaction unit.

---

## 5. The `research-op` skill architecture

### 5.1 Thin SKILL.md + heavy scripts + forked context

The architectural rule: **the skill body is the contract, the scripts are the implementation.** The 33-row matrix, the composite-event surface map, the 18-state transition table, and the validate logic never live in SKILL.md prose. They live in Python scripts the skill body invokes.

Reasons:
- Claude Code Skills degrade with body size (obra/superpowers' empirical finding from running 14 skills under load).
- The matrix is data, not prose — Python dict in `transitions.py` is easier to maintain than a prose table.
- The agent reads the skill body once on invocation; it does not need to internalize the 33 rows to make a single mutation. It picks an op or event, calls the script, reads the structured response.

Plus a second defense: the SKILL.md frontmatter declares `context: fork`. Every `/research-op` invocation runs in a **forked subagent context** — the routing/validation work does not accumulate in the main agent's context window. The main agent gets back a one-line summary and goes back to its own work.

### 5.2 The skill's file tree

```
skills/research-op/
├── SKILL.md                          (~150 lines, contract-only)
├── references/
│   ├── matrix.md                     (full 33-row Insert/Update/Delete/Check matrix from § 4)
│   ├── composite-events.md           (5 named events: chain-done, checkpoint-saved, sentinel-write,
│   │                                   phase-marker, candidate-json — with their fan-out surface lists)
│   ├── validate-rules.md             (Pattern B reject-before-write rule catalogue)
│   └── state-machine.md              (18-cell (category, status) machine + lane-crossing T1 rules)
└── scripts/
    ├── research_op.py                # CLI entry; thin dispatcher. <100 lines.
    ├── transitions.py                # 33-row matrix as a Python dict. Pure data. <300 lines.
    ├── events.py                     # 5 composite events as {event: [(op, target), ...]} dicts. <150 lines.
    ├── validate.py                   # Pattern B reject-before-write checks. Wraps learnings_lint subset. <400 lines.
    ├── router.py                     # Looks up (category, status, op, target) in transitions; dispatches. <150 lines.
    ├── audit.py                      # Appends to var/research/<pkg>/_actions.jsonl. <80 lines.
    ├── scan_events.py                # Replaces propagate_facts.py role 1: artifact mtime scanner. <200 lines.
    └── ops/
        ├── insert.py                 # Per-op handlers; each <250 lines.
        ├── update.py
        ├── delete.py
        └── check.py
```

### 5.3 SKILL.md frontmatter and section budget

```yaml
---
name: research-op
description: "<= 1500 chars; the WHEN to invoke + safety claims + accepted invocation shapes>"
allowed-tools: Bash(python3 scripts/* ...), Read, Edit, Write, Grep, Glob
context: fork                    # isolate routing/validation from main agent
disable-model-invocation: false  # model can call autonomously
---
```

Body section budget (target: ≤ 150 lines):

| Section | Approx lines |
|---|---|
| Purpose | 10 |
| Invocation (both structured and natural-language shapes) | 25 |
| Preconditions (package exists, runtime root resolved, cursor accessible) | 15 |
| Op surface (primitives + named events; pointer to references/matrix.md) | 15 |
| Validate-before-write contract (pointer to references/validate-rules.md) | 15 |
| On reject (structured-observation envelope + retry rule) | 10 |
| Audit log (location, format) | 10 |
| Single-home invariants this skill protects (3 invariants from § 4.5) | 15 |
| Pointers (references/, scripts/) | 10 |
| Bundled resources (scripts/ + references/ list) | 10 |

### 5.4 The two invocation shapes

**Structured form** (agent autonomous · WORKFLOW.md step handlers · scan-events):

```bash
/research-op --pkg <id> --op insert --target methodsTried --payload '{...}'
/research-op --pkg <id> --event chain-done --payload '{"artifact": "..."}'
/research-op --pkg <id> --op check --scope all
```

**Natural-language form** (user manual override · ad-hoc fixes):

```bash
/research-op update "set status of 2026-05-15-panda-baselines to BLOCKED, reason: GPU contention until Tuesday"
/research-op insert "add a new docs page under panda-baselines for the rerank ablation"
/research-op delete "remove the dead resource-allocation row P3-shard-7 from panda-baselines tracker"
/research-op check  "audit panda-baselines for missing methodsTried evidence"
/research-op event  "treat candidate.json under panda-baselines/output/Phase2 as a checkpoint-saved event"
```

**Skill-body pipeline when natural-language form is invoked:**

1. Detect shape — presence of `--pkg` / `--op` flags vs free-form prose.
2. Parse prose into structured `{pkg, op, target, payload}` using the skill's own LLM context.
3. Print the parsed structured form back to the user as a single preview line:
   `→ resolved: --pkg 2026-05-15-panda-baselines --op update --target status --to BLOCKED --field currentBlocker="GPU contention until Tuesday"`
4. Run Phase 1 state-gate + Phase 2 invariant-check (Pattern B).
5. If both pass → apply the write + append to audit log + return `✓` to the user.
6. If either rejects → return the structured reject envelope so the user sees the rule violation and can re-issue.

**Guarantee preservation:** the natural-language form is just a front parser; it always converts to the structured form before any write attempt. Pattern B fires the same way. The audit log captures the natural-language prose verbatim in a `user_intent` field alongside the parsed structured form, so post-hoc you can see what the user asked for vs what was actually written.

### 5.5 Sequence of one op call (what happens inside the forked subagent)

1. Parse `--pkg`, `--op`, `--target`, `--payload` (or `--event`, `--payload`, or natural-language prose).
2. If natural-language: parse to structured form; show preview line.
3. Read `(category, status)` from inventory.
4. Look up `(category, status, op, target)` in `transitions.py` → legal or `RejectIllegalState`.
5. Run pre-write validators from `validate.py` against the payload → legal or `RejectInvariantViolation` with `{rule, field, suggested-fix}`.
6. Apply the write (inventory edit for inventory targets; in-place anchor edit for non-painted sections; new-file write for `docs/<slug>.html`).
7. Bump `<time data-field="last-updated">` on every touched HTML file.
8. Append one line to `var/research/<pkg>/_actions.jsonl`.
9. Return a one-line success summary to the main agent (forked context discards the rest).

On any reject (steps 4 or 5), **no bytes hit disk.** The reject envelope is the structured observation `{phase, rule, file, anchor, field, expected, actual, suggested_fix}` from SWE-agent's Pattern B.

---

## 6. Write-time validate (Pattern B) — what it solves and how

### 6.1 What this section solves

The end-of-turn lint pipeline today catches violations after the agent has already written broken content. The two failure modes from § 1 (F1 cascading corruption, F2 silent stuck loops) both stem from this lag.

**Pattern B moves validation to the moment before each write.** Cascading corruption stops at the first link — a rejected write does not fire its downstream propagation events. Stuck loops become visible immediately via the audit log.

### 6.2 Two-phase check

**Phase 1 — State gate** (cheap, from `transitions.py`):
> Is `(category, status, op, target)` in the legal-transition table?

**Phase 2 — Invariant check** (the SWE-agent reject-before-write claim):
> Given that this op is legal in this state, does the payload satisfy every invariant that applies to this target?

The rule catalogue lives in `references/validate-rules.md` and is implemented in `validate.py`. Examples per target:

| Target | Phase 2 rules |
|---|---|
| `methodsTried[]` row (I2) | All 6 fields present · `verdict ∈ {pass, fail, inconclusive}` · `evidencePath` resolves · source `results.html#<anchor>` exists |
| result-gate row (I6) | All 10 columns present · `Validity ∈ {ok, partial, fail, unmeasured}` · if `verdict=pass`: P5 triple-check (hypothesis · metric/dataset/protocol · evidence-manifest dataset) all string-equal to frozen contract |
| result block (I7) | 6-part canon present: title + block-summary (≤ 25 words) + block-detail + main table + block-insight + (block-ablation or explicit empty) · ablation `<details>` closed by default |
| verdict cell (U10) | Mechanically computed from `success.predicate(measured)` — refuse if prose contradicts the predicate (P5) |
| lane-crossing status (U1) | T1 ack token present at destination's `data-ack` slot · destination cell's required-fields all present · transition edge legal per `schema.js` |
| new doc file + card (I9) | File path under `packages/<pkg-id>/docs/` · paired doc card written atomically · card has 6-part shape + 5 `data-doc-*` attrs · group-rationale present on parent section |
| `methodsTried[]` Delete (D4) | `(category, status) ∈ in-progress/*` only — terminal-frozen cells refuse |

### 6.3 Structured reject envelope

```json
{
  "rejected": true,
  "phase": "state-gate" | "invariant-check",
  "rule": "p5-hypothesis-mismatch",
  "file": "research_html/packages/<pkg>/results.html",
  "anchor": "#exp-p1",
  "field": "verdict",
  "expected": "predicate(success) -> fail (measured=0.812 < gate=0.85)",
  "actual":   "verdict=pass written by agent",
  "suggested_fix": "Set verdict=fail; the measured value does not pass success.predicate."
}
```

### 6.4 Stop-Gate becomes defense-in-depth

`learnings_lint.py all` continues to run at the Stop-Gate. With Pattern B in place it should almost always return clean. It still catches:

- Manual edits the user made outside `research-op` (the "user opens the HTML and types" path).
- Cursor drift if a write went around the system.
- Cross-package consistency rules (`research-op` only sees one package; lint sees the whole project).

Non-empty Stop-Gate report remains a workflow violation per existing rules — no change there.

---

## 7. Local audit log — what it solves and how

### 7.1 Why a log replaces the rejected per-op git commit

The peer-framework survey recommended per-op git commits (Aider's pattern) as the audit log. The user rejected this — package files are working files, not source-controlled artifacts, and the agent should never invoke git. Replacement: a local append-only jsonl that gives the same observability without involving git.

### 7.2 Location and format

**Location:** `var/research/<pkg>/_actions.jsonl`

- Under `var/research/...` so it is **not git-tracked** (matches CLAUDE.md's existing rule).
- Per-package so `tail -f` works without grep gymnastics.
- Append-only JSONL — easy to parse, easy to grep, no schema migration needed if a field changes.
- Goes with the runtime root when the package archives.

**Format (one line per op invocation):**

```json
{
  "ts": "2026-05-24T15:42:31.847+10:00",
  "pkg": "2026-05-15-panda-baselines",
  "op": "insert",
  "target": "methodsTried",
  "event": null,
  "state_before": {"category": "in-progress", "status": "RESULT_ANALYSIS"},
  "state_after":  {"category": "in-progress", "status": "RESULT_ANALYSIS"},
  "validation": "passed",
  "rule": null,
  "files_touched": ["research_html/data/research-packages.js"],
  "agent": "main",
  "user_intent": null,
  "duration_ms": 84,
  "payload_sha256": "9c3f...",
  "payload": { "method": "...", "hypothesis": "...", "gate": "...",
               "measured": "...", "verdict": "pass",
               "evidencePath": "results.html#exp-p1" }
}
```

**Verbatim payload** is included by default (research data carries no PII concern; replay + post-hoc debug are valuable). For composite events, one line covers the fan-out; `files_touched` lists every surface the event wrote. For natural-language invocations, `user_intent` carries the original prose verbatim alongside the parsed structured form.

**Failed attempts are logged** (with `validation: "rejected"` and the rule id). This is the primary debug surface for "why is the agent stuck": grep `"validation": "rejected"` and read the most recent entries.

### 7.3 What the audit log makes possible

1. `tail -f var/research/<pkg>/_actions.jsonl` — live observability of every op the agent attempts.
2. `grep '"validation": "rejected"' _actions.jsonl | tail -20` — see the agent's recent reject pattern; diagnose stuck loops in seconds.
3. Per-event `files_touched` list — verify Fact Propagation Contract atomicity post-hoc.
4. The 10-min `§5 status line` (one line per open exp) becomes auto-derivable from the most-recent `EXPERIMENT_RUNNING` event entry.
5. **Dashboard Pending Actions card** (M6.1) can include "N recent rejects in `<pkg>`" by grepping each package's log — surfaces agent-stuck states for the user without polling every package's HTML.

---

## 8. Trigger model + composition with WORKFLOW.md and the 3 existing skills

### 8.1 Three trigger sources, one entry point

`research-op` has exactly one CLI but three distinct callers:

| Trigger | Cadence | Typical calls |
|---|---|---|
| **(T-W) WORKFLOW.md per-step handler** | Once per workflow state transition (~once per turn) | `Update` (status field), `Insert` (impl-review row, result-gate row, result block), terminal-lane `Update` (T1-acked) |
| **(T-E) Artifact event scanner** (replaces propagate_facts.py) | On every per-turn live cycle while a run is open | Composite `event` calls: chain-done, checkpoint-saved, sentinel-write, phase-marker, candidate-json |
| **(T-U) User slash command** | Rare (manual fixes only) | Natural-language `update` / `insert` / `delete` / `check` for ad-hoc overrides |

### 8.2 Skill composition

```
LAYER             SKILL                    FREQUENCY     SCOPE
─────────────────────────────────────────────────────────────────────────
Project-init  →   research-dashboard       once/project  Scaffold research_html/, schema.js, learnings.html
Package-init  →   research-package         once/pkg      Scaffold the fixed file set + first inventory entry
Editorial     →   research-analysis        mid-freq      Rules + Insights on analysis.html (delegates writes to research-op)
Mutation      →   research-op (NEW)        per-turn      All other ops: Insert / Update / Delete / Check
```

- **`research-dashboard`** unchanged. Independent of `research-op`.
- **`research-package`** unchanged for scaffold. After scaffold, the "post-scaffold patch checklist" (~15 fields filled with `unmeasured`) becomes the first sequence of `research-op update` calls.
- **`research-analysis`** owns editorial discipline for analysis.html (when to add a rule, what counts as an insight) but delegates file writes to `research-op insert --target analysis-rule` and `--target analysis-insight`. **Editorial layer for content, mutation layer for format.**

### 8.3 Composition with WORKFLOW.md

WORKFLOW.md keeps all 7 steps and the 11 workflow-states. **One new rule** added:

> **Mutation rule.** Every mutation to a package surface (HTML files, inventory entry, doc files) MUST go through `/research-op`. Direct `Edit` / `Write` on package files is a workflow violation. The only exceptions are (a) `research-package` / `research-dashboard` at scaffold time, and (b) the user typing in their editor outside the agent.

WORKFLOW.md step → `research-op` mapping:

| Step | Typical research-op calls |
|---|---|
| 1. Load Context | `research-op check --pkg <id> --scope all` (read-only) |
| 2. Implement | `insert --target impl-review-row`; `update --target status --to IMPLEMENTATION_REVIEW` |
| 3. Review | `update --target impl-review-row.verdict`; on pass: `update --target status --to READY_TO_LAUNCH` (T1 ack) |
| 4. Launch | `insert --target resource-allocation-row`; `update --target status --to EXPERIMENT_RUNNING` (T1 ack) |
| 5. Live | `insert --target live-check-row` (per 10-min); `event --name checkpoint-saved / phase-marker / chain-done` |
| 6. Analyze | `insert --target result-gate-row`; `insert --target result-block`; `insert --target methodsTried-row` (E1) |
| 7. Next Action | `update --target chosen-route`; `update --target status --to NEXT_ACTION_READY` |
| Stop Gate | `research-op check --pkg <id> --scope all` (defense-in-depth) |

### 8.4 What happens to `propagate_facts.py`

`propagate_facts.py` had two roles bundled: (1) artifact mtime scanner, (2) fan-out instruction printer. In the new design, both collapse into `research-op`:

- Role 1 → `scripts/scan_events.py` inside `research-op`, callable via `/research-op scan-events --pkg <id>`.
- Role 2 → `/research-op event --name <type>` with Pattern B fan-out validation.

The shipped `propagate_facts.py` byte-copy in each package's `scripts/` is removed. Existing CLAUDE.md / WORKFLOW.md text mentioning `propagate_facts.py` needs updating (~5 spots, captured in § 11 migration TODO).

### 8.5 User-visible surface after this design lands

```
/research-dashboard     — scaffold global dashboard         (existing, ~unchanged)
/research-package       — scaffold one package              (existing, ~unchanged)
/research-analysis      — add rule/insight (editorial)      (existing, now delegates writes)
/research-op            — every other mutation              (NEW)
```

User workflow:
1. `/research-dashboard` once per project.
2. `/research-package <slug>` to start a direction.
3. From this point: **the agent autonomously calls `/research-op` per turn** via WORKFLOW.md's per-step handlers + per-event scanner. The user reads HTML pages and types T1 acks into `data-ack` slots when they appear. The user does not invoke `/research-op` in normal operation.
4. `/research-op <op> "<natural-language prose>"` is available to the user any time as an ad-hoc override — Pattern B validates and rejects the same way as agent calls.
5. `/research-analysis` only when the user (or agent) wants to write a rule or distill an insight from results.

This delivers the user's stated goal — *"the research-package is maintained by agent-only, the user don't need to do any further instruction for the package"* — while keeping P2 typed acks intact at terminal transitions and giving the user a release valve at any moment.

---

## 9. New data-* attributes and code surfaces this design introduces

Most attributes already exist (`data-ack`, `data-ack-value`, `data-section`, `data-field`, `data-table-body`, `data-validity`, `data-audience`). This design adds none to HTML — it relies on the existing attributes. New surfaces are all in Python / scripts:

| Surface | Role |
|---|---|
| `skills/research-op/SKILL.md` | NEW — ~150-line thin contract |
| `skills/research-op/references/*` | NEW — 4 reference docs (matrix, composite-events, validate-rules, state-machine) |
| `skills/research-op/scripts/*` | NEW — 9 Python modules (CLI + dispatcher + matrix + events + validate + router + audit + scan_events + 4 op handlers) |
| `var/research/<pkg>/_actions.jsonl` | NEW per-package — local audit log, append-only |
| `var/research/<pkg>/manifests/.propagation_cursor` | EXISTING — kept; ownership transfers to `scan_events.py` |
| `WORKFLOW.md` — new Mutation rule paragraph | EDIT — 1 paragraph added |
| `CLAUDE.md` — Protocol 3 (Fact Propagation Contract) updates | EDIT — replace `propagate_facts.py` references with `/research-op scan-events` and `/research-op event` |
| Per-package `scripts/propagate_facts.py` byte-copy | REMOVE — superseded by `research-op` |

---

## 10. Handoff to writing-plans

This spec is a **design contract**, not an implementation plan. Inputs that the `writing-plans` skill needs to break this into concrete tasks:

1. **This spec** (skill architecture + matrix + validate rules + audit log + composition).
2. **The companion HTML-design spec** ([`2026-05-24-trustworthy-pipeline-html-design.md`](2026-05-24-trustworthy-pipeline-html-design.md)) — provides the page/section/anchor canon that this spec's validate rules check against.
3. **The current 3 skills' SKILL.md files** — `research-package`, `research-dashboard`, `research-analysis` — as the surrounding context the new skill plugs into.
4. **`research_html/data/schema.js`** — the canonical 18-cell state machine + required-field rules; `transitions.py` derives from it.
5. **The existing `learnings_lint.py`** — the rule set that becomes the seed for `validate.py`'s Phase 2 catalogue (the existing rules become write-time rules).

Expected outputs from `writing-plans`:

1. **Phase 1: skill scaffold.** Write `skills/research-op/SKILL.md` (thin) + `references/*.md` (4 files) + `scripts/research_op.py` CLI + `scripts/transitions.py` (the 33-row table) + `scripts/audit.py`. Smoke-test on the panda-baselines package.
2. **Phase 2: Pattern B validators.** Build `scripts/validate.py` rule catalogue, port the relevant subset of `learnings_lint.py` checks to write-time form. Add the structured reject envelope.
3. **Phase 3: op handlers + composite events.** Implement `scripts/ops/{insert,update,delete,check}.py` and `scripts/events.py` for the 5 named composite events. Migrate `propagate_facts.py` role 1 to `scripts/scan_events.py`.
4. **Phase 4: WORKFLOW.md + CLAUDE.md migration.** Add the Mutation rule. Replace `propagate_facts.py` mentions. Update the 5-protocol stack to reference `/research-op`.
5. **Phase 5: research-analysis delegation rewrite.** Update `research-analysis` SKILL.md to delegate writes to `research-op insert --target analysis-rule` / `--target analysis-insight`.
6. **Phase 6: panda-baselines pilot.** Run the new skill on the canonical example package end-to-end. Compare per-op audit log entries against the existing tracker / results history. Iterate.
7. **Phase 7: roll out to other 5–6 packages.** Run `research-op check` on each; let the agent run `update` ops to bring them to spec.

---

## 11. Cross-package + cross-system migration TODO

Deferred items captured for the writing-plans / implementation phase:

| # | Item | Owner | Estimated touch |
|---|---|---|---|
| M1 | Remove `propagate_facts.py` byte-copies from existing packages' `scripts/` | rollout | ~7 packages |
| M2 | Update `CLAUDE.md` mentions of `propagate_facts.py` | rollout | ~5 spots |
| M3 | Update `WORKFLOW.md` mentions of `propagate_facts.py` + add Mutation rule paragraph | rollout | ~3 spots + 1 new |
| M4 | Update `research_html/scripts/learnings_lint.py` to coexist with write-time validation (no double-counting) | rollout | 1 file |
| M5 | Update `research-package` SKILL.md: replace "Fact Propagation Contract" mechanical-check section with "delegates to `/research-op scan-events`" | rollout | 1 file |
| M6 | Update `research-analysis` SKILL.md to delegate writes to `research-op` | rollout | 1 file |
| M7 | Update `package-template.html` / `next-action` migration from companion spec | follow-on | shared with companion spec migration |
| M8 | Add per-package `var/research/<pkg>/_actions.jsonl` log files for already-existing packages (initial empty) | rollout | ~7 packages |
| M9 | Add `_actions.jsonl` to `.gitignore` if not already covered by `var/` | rollout | 1 file |

---

## 12. Open decisions deliberately deferred

1. **What exactly counts as "natural-language" parse-failure** — when the user's prose is so ambiguous the skill can't produce a structured form. Should the skill ask a clarifying question, refuse, or guess? Defer to implementation; the user's first session with `/research-op <op> "..."` will surface what's needed.
2. **Whether composite event names need to be extensible per-project** — today the 5 events are universal (chain-done, checkpoint-saved, sentinel-write, phase-marker, candidate-json). A future project may need a 6th. Defer until a real need surfaces.
3. **How `/research-op` interacts with `tmux` session monitoring** — the Live state involves tmux sessions; the audit log may want to capture `tmux` session IDs as `files_touched` analogs. Defer to Phase 1 implementation.
4. **Whether the `references/` files are also subject to size discipline** — if `references/matrix.md` grows past ~500 lines, does it become two files? Pragmatic call at implementation time.
5. **Whether to add a `--dry-run` mode at the top level** — would let the user / agent preview a write without applying it. Mentioned in passing for `check` (`C3 → --dry-run`); generalize or not is a UX call for implementation.

---

## 13. Spec self-review

| Check | Result |
|---|---|
| **Placeholder scan**: any "TBD" / "TODO" / vague requirements? | None remaining — all 5 open decisions in § 12 are explicitly deferred with reason. |
| **Internal consistency**: do sections contradict each other? | Cross-checked: § 4 matrix matches § 5.2 scripts/ tree (transitions.py = matrix data); § 6 validate examples match § 4 row constraints; § 8 trigger model matches § 5.4 invocation shapes. |
| **Scope check**: focused enough for one implementation plan? | Yes — 7 implementation phases (§ 10), all in one skill + scripts directory. No platform changes, no cross-system refactors beyond the migration TODO. |
| **Ambiguity check**: any requirement readable two ways? | The five locked decisions in § 3 explicitly resolve the ambiguities the brainstorm surfaced (hybrid grain, single skill, no git, Init outside, matrix-keys = `(category, status)` only). |
| **Architecture coherence**: does the design defend the three failure modes named in § 1? | F1 cascading corruption → Pattern B reject-before-write breaks the chain at the first link. F2 silent stuck loops → audit log makes rejects visible via `tail -f`. F3 format drift → single mutation chokepoint + write-time validators against the canonical rule set. |
| **Composition coherence**: does this slot under WORKFLOW.md + the 3 existing skills without breaking them? | Yes — § 8 explicitly maps WORKFLOW.md steps onto `research-op` calls; existing skills keep their roles; only the per-package `propagate_facts.py` byte-copy is removed (§ 11.M1). |
| **Deep-research traceability**: do design choices cite the survey? | Pattern A → LangGraph (§ 2). Pattern B → SWE-agent (§ 2, § 6). Pattern C rejection → user override of Aider pattern (§ 2, § 3.D3). Anti-pickle → Agent Laboratory (§ 2). Thin-skill discipline → obra/superpowers (§ 5.1). |
| **G1 / G2 / G3 alignment**: every design choice traces to a principle? | G1 (user control) → audit log + natural-language user-invocation (§ 5.4, § 7) + Pending Actions card (§ 7.3). G2 (faithfulness) → Pattern B prevents drift writes (§ 6.2) + verbatim payload audit trail (§ 7.2). G3 (bounded context) → forked context per invocation + thin SKILL.md + matrix as data not prose (§ 5.1). |
