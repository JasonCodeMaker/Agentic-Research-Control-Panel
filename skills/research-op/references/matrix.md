# research-op — Legality matrix

This file is the authoritative source for `(category, status, op, target)` legality.
`scripts/transitions.py` is generated from this matrix; if you change a row here,
update `transitions.py` in the same commit.

### 4.1 Insert — add row / card / section / new file

| # | Target | Legal in `(category, status)` | Constraint / source |
|---|---|---|---|
| I1 | `experiments[]` row → paints plan.html + index.html | `(in-progress, CONTEXT_LOADED / IMPLEMENTING / READY_TO_LAUNCH)` | Pre-launch only; obeys 12-word `purpose` cap, atomic `gate` |
| I2 | `methodsTried[]` row → paints learnings.html | `(in-progress, RESULT_ANALYSIS / NEXT_ACTION_READY)` + during T1 ack window for `(success, *)` / `(fail, *)` | Source: results.html result-gate row with verdict + verified `evidencePath` (E1) |
| I3 | tracker live-check row | `(in-progress, EXPERIMENT_RUNNING / LIVE_ANALYSIS)` | One row per open exp; replaces prior row for same `exp_id` |
| I4 | tracker resource-allocation row | `(in-progress, READY_TO_LAUNCH → EXPERIMENT_RUNNING)` | One per planned exp |
| I5 | tracker impl-review row | `(in-progress, IMPLEMENTATION_REVIEW / IMPLEMENTING)` | One per `change_id` |
| I6 | results.html result-gate row | `(in-progress, EXPERIMENT_RUNNING → RESULT_ANALYSIS)` | One per planned experiment (P0, P1, …); not per measurement |
| I7 | results.html result block (6-part canon) | `(in-progress, RESULT_ANALYSIS)` | One per result group; obeys canonical 6-part shape |
| I8 | analysis.html rule / insight subblock | any `(in-progress, *)` after ≥ 1 finalized result-gate row | Owner skill: `research-analysis` (delegates writes to `research-op`) |
| I9 | `docs/<slug>.html` (new file) + paired doc card | any non-terminal cell | Group-design rule applies; card + file written atomically |
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
