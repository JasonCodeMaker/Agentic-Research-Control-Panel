# Whole Pipeline Fact System Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move tracker live checks, tracker resource allocation rows, and `methodsTried` rows onto canonical CSV facts while keeping the current dashboard and registry consumers working through generated projections.

**Architecture:** Build on Phase 1's `lib/package_facts` module. Add CSV schemas for `live_checks.csv`, `resource_allocation.csv`, and `methods_tried.csv`; extract live tracker facts from real `outputs/<pkg>/runs/<run_id>/status.json`; render `tracker.html` ledger rows from CSV; make `research-packages.js methodsTried[]` a compatibility projection generated from `methods_tried.csv`; extend lint and `research-op` so fact-backed packages do not hand-edit duplicated tracker/method rows.

**Tech Stack:** Python 3.13 stdlib, CSV, JSON, existing `status.json` contract, existing `research-op`, existing `learnings_lint.py`, existing pytest suite.

---

## Preconditions

- Phase 1 is landed first.
- `lib/package_facts` exists and exposes CSV read/upsert helpers, source refs, and file revisions.
- `skills/research-package/scripts/render_result_facts.py` and `skills/research-package/scripts/extract_result_table.py` are present from Phase 1.
- Existing legacy packages remain readable. New fact-backed tracker/method changes must write CSV first and render projections second.

## File Structure

- Modify `lib/package_facts/__init__.py`: add table column constants and validation helpers for tracker and methods facts.
- Create `skills/research-exp-live/scripts/extract_tracker_facts.py`: read real `status.json` snapshots into `live_checks.csv` and `resource_allocation.csv`.
- Create `skills/research-package/scripts/render_tracker_facts.py`: render tracker live-check and resource-allocation tables from CSV.
- Create `skills/research-package/scripts/append_methods_tried_fact.py`: append a `methods_tried.csv` row from a source CSV row reference.
- Create `skills/research-package/scripts/sync_methods_tried_projection.py`: regenerate the package's `methodsTried[]` compatibility array from `methods_tried.csv`.
- Modify `skills/research-op/scripts/ops/insert.py`: route fact-backed tracker/method inserts through CSV writers and renderers.
- Modify `skills/research-op/scripts/events.py`: fix `CHECKPOINT_SAVED` tracker fanout to use legal insert targets and the fact-backed projection path.
- Modify `skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py`: extend fact alignment checks to tracker and methods projections.
- Modify `skills/research-package/templates/tracker.html`: add fact-backed projection anchors for new packages.
- Modify `skills/research-package/references/package-contract.md` and `skills/research-exp-live/references/status-contract.md`: document Phase 2 ownership.
- Add tests under `tests/package_facts/`, `tests/exp_live/`, `tests/research-dashboard/`, and `tests/research-op/`.

---

### Task 1: Tracker and Methods CSV Schemas

**Files:**
- Modify: `lib/package_facts/__init__.py`
- Test: `tests/package_facts/test_tracker_methods_schema.py`

- [ ] **Step 1: Write failing schema tests**

Create `tests/package_facts/test_tracker_methods_schema.py` with tests that assert these constants exist exactly:

```python
from lib import package_facts


def test_live_check_columns_include_view_columns_and_provenance():
    assert package_facts.LIVE_CHECK_COLUMNS == [
        "row_id", "time", "exp_id", "run_id", "agent", "run_state",
        "last_log", "progress", "metrics", "resource", "artifacts",
        "eta", "action", "next_check", "source_artifact", "source_mtime",
        "extractor", "extracted_at",
    ]


def test_resource_allocation_columns_include_tracker_columns_and_provenance():
    assert package_facts.RESOURCE_ALLOCATION_COLUMNS == [
        "row_id", "exp_id", "purpose", "dependency", "target", "capacity",
        "assigned", "reason", "agent", "command_cwd_env", "session_job",
        "runtime_root", "log_path", "expected_duration", "status",
        "source_artifact", "source_mtime", "extractor", "extracted_at",
    ]


def test_methods_tried_columns_keep_registry_shape_and_source_ref():
    assert package_facts.METHODS_TRIED_COLUMNS == [
        "row_id", "exp_id", "method", "hypothesis", "gate", "measured",
        "verdict", "evidencePath", "source_table", "source_row",
        "source_artifact", "extracted_at",
    ]
```

Add one test that writes one row for each table with `upsert_csv_rows()` and verifies the header order is stable.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_tracker_methods_schema.py
```

Expected: failures because the new constants are missing.

- [ ] **Step 3: Implement the constants and validation helpers**

In `lib/package_facts/__init__.py`, add:

- `LIVE_CHECK_COLUMNS`
- `RESOURCE_ALLOCATION_COLUMNS`
- `METHODS_TRIED_COLUMNS`
- `VALID_RUN_STATES = {"QUEUED", "RUNNING", "COMPLETED", "RUN_FAILED", "RUN_HALTED", "STALE", "SKIPPED"}`
- `table_csv_path(pkg, table_name, root=Path("."))` returning `fact_paths(pkg, root).tables_dir / f"{table_name}.csv"`

Keep validation light: schema helpers verify required row ids and enum values, while extractors own source-specific validation.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_schema.py tests/package_facts/test_tracker_methods_schema.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add lib/package_facts/__init__.py tests/package_facts/test_tracker_methods_schema.py
git commit -m "Add tracker and methods fact schemas"
```

---

### Task 2: Extract Tracker Facts From Real status.json

**Files:**
- Create: `skills/research-exp-live/scripts/extract_tracker_facts.py`
- Test: `tests/exp_live/test_extract_tracker_facts.py`

- [ ] **Step 1: Write failing extractor tests**

Create tests with a real temporary `outputs/<pkg>/runs/<run_id>/status.json` snapshot containing:

```json
{
  "run_id": "P1-r1",
  "pkg": "2026-06-11-demo",
  "exp_id": "P1",
  "status": "RUNNING",
  "progress": {"epoch": 2, "total": 10, "percent": 20},
  "latest_metrics": {"Recall@1": 42.1},
  "source_map": {"Recall@1": "outputs/2026-06-11-demo/runs/P1-r1/eval.json"},
  "resource": {"gpu": "0", "mem_gb": 19.5},
  "eta": "unknown",
  "last_output_at": 1781139600,
  "started_at": 1781136000
}
```

Test command:

```bash
python3 skills/research-exp-live/scripts/extract_tracker_facts.py \
  --repo-root "$TMP" \
  --status outputs/2026-06-11-demo/runs/P1-r1/status.json \
  --agent codex \
  --live-action CONTINUE_RUN \
  --next-check 2026-06-11T10:30:00+10:00
```

Assertions:

- `research_html/data/packages/2026-06-11-demo/tables/live_checks.csv` exists.
- The live row has `row_id=P1:P1-r1`, `exp_id=P1`, `run_id=P1-r1`, `run_state=RUNNING`, `metrics` as compact sorted JSON, `source_artifact` pointing to the status file.
- `resource_allocation.csv` exists and has `row_id=P1:P1-r1`, `status=RUNNING`, `runtime_root=outputs/2026-06-11-demo/runs/P1-r1`.
- Missing `status.json` returns exit code `2` and writes no CSV.
- A malformed `status.json` returns exit code `2` and writes no CSV.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/exp_live/test_extract_tracker_facts.py
```

Expected: failure because the extractor script does not exist.

- [ ] **Step 3: Implement the extractor**

Create `skills/research-exp-live/scripts/extract_tracker_facts.py`:

- Resolve repo root from `--repo-root`.
- Read only the supplied `--status` file.
- Validate required keys: `run_id`, `pkg`, `exp_id`, `status`.
- Reject status values outside `package_facts.VALID_RUN_STATES`.
- Build `time` and `last_log` from `last_output_at` when present; otherwise use empty string.
- Serialize `progress`, `latest_metrics`, and `resource` with `json.dumps(..., sort_keys=True, separators=(",", ":"))`.
- Write one row into `live_checks.csv` using `LIVE_CHECK_COLUMNS`.
- Write one row into `resource_allocation.csv` using `RESOURCE_ALLOCATION_COLUMNS`.
- Set `source_mtime` from the `status.json` mtime and `extracted_at` from current local time.
- Never infer experiment results from live metrics; this extractor only writes tracker tables.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/exp_live/test_extract_tracker_facts.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add skills/research-exp-live/scripts/extract_tracker_facts.py tests/exp_live/test_extract_tracker_facts.py
git commit -m "Extract tracker facts from live status snapshots"
```

---

### Task 3: Render Tracker HTML From CSV Facts

**Files:**
- Create: `skills/research-package/scripts/render_tracker_facts.py`
- Modify: `skills/research-package/templates/tracker.html`
- Test: `tests/package_facts/test_render_tracker_facts.py`

- [ ] **Step 1: Write failing renderer tests**

Create tests that set up:

- a minimal `research_html/packages/<pkg>/tracker.html` with both table bodies:
  - `<tbody data-table-body="live-check">`
  - `<tbody data-table-body="live-check-history">`
  - `<tbody data-table-body="resource-allocation">`
- `live_checks.csv` with 6 rows sorted by `time`;
- `resource_allocation.csv` with 2 rows.

Assertions after running the renderer:

- latest 5 live rows appear in `[data-table-body="live-check"]`;
- the oldest live row appears in `[data-table-body="live-check-history"]`;
- resource rows appear in `[data-table-body="resource-allocation"]`;
- the live table has `data-source="tables/live_checks.csv"` and `data-fact-revision="sha256:..."`;
- each value-bearing live row includes `data-source-row="live_checks:<row_id>"`;
- the renderer preserves `#resume-block`, `#chosen-route`, and the todo list.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_render_tracker_facts.py
```

Expected: failure because `render_tracker_facts.py` does not exist.

- [ ] **Step 3: Add template anchors**

In `skills/research-package/templates/tracker.html`:

- add `data-fact-projection="tracker"` to the live-check article;
- add `data-fact-projection="resource-allocation"` to the resource-allocation article;
- keep existing `data-table-body` selectors unchanged.

- [ ] **Step 4: Implement the renderer**

Create `skills/research-package/scripts/render_tracker_facts.py`:

- CLI args: `--repo-root`, `--pkg`.
- Read `live_checks.csv` and `resource_allocation.csv`.
- Sort live rows by `time` descending; rows with empty `time` sort last.
- Render the first 5 rows into `live-check`; render the rest into `live-check-history`.
- Render all resource rows in CSV order.
- Add `data-source`, `data-fact-revision`, and `data-source-row` markers.
- Escape all HTML cell values with `html.escape`.
- Reject malformed CSV with exit code `2` and leave the previous HTML unchanged.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_render_tracker_facts.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add skills/research-package/scripts/render_tracker_facts.py skills/research-package/templates/tracker.html tests/package_facts/test_render_tracker_facts.py
git commit -m "Render tracker ledgers from CSV facts"
```

---

### Task 4: Methods Tried CSV and Compatibility Projection

**Files:**
- Create: `skills/research-package/scripts/append_methods_tried_fact.py`
- Create: `skills/research-package/scripts/sync_methods_tried_projection.py`
- Test: `tests/package_facts/test_methods_tried_fact_projection.py`

- [ ] **Step 1: Write failing tests**

Create tests that:

- write `result_table_P1.csv` with `row_id=current_best`, `metric=Recall@1`, `value=42.1`, `unit=%`, `verdict=PASS`, `source_artifact=outputs/pkg/run/summary.json`;
- run `append_methods_tried_fact.py --source-ref result_table_P1:current_best --method "P1 reranker" --hypothesis "Reranking improves Recall@1" --gate "Recall@1 > 40.0"`;
- assert `methods_tried.csv` has `measured="Recall@1=42.1%"`, `verdict=PASS`, `source_table=result_table_P1`, `source_row=current_best`, `evidencePath=outputs/pkg/run/summary.json`;
- run `sync_methods_tried_projection.py`;
- assert `research_html/data/research-packages.js` contains a `methodsTried` row with only the existing six dashboard fields: `method`, `hypothesis`, `gate`, `measured`, `verdict`, `evidencePath`.

Add a second test:

- when the source row has `source_type=manual` and `verdict=PASS`, `append_methods_tried_fact.py` exits `2` and writes no CSV row.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_methods_tried_fact_projection.py
```

Expected: scripts are missing.

- [ ] **Step 3: Implement `append_methods_tried_fact.py`**

Implementation requirements:

- CLI args: `--repo-root`, `--pkg`, `--exp-id`, `--source-ref`, `--method`, `--hypothesis`, `--gate`, optional `--row-id`.
- Resolve `--source-ref` using `package_facts.find_row_by_ref()`.
- Compose `measured` as `<metric>=<value><unit>` with no added spaces.
- Use source row `verdict`; default empty verdict to `INCONCLUSIVE`.
- Use source row `source_artifact` as `evidencePath`.
- Reject manual PASS rows.
- Upsert into `methods_tried.csv` using `METHODS_TRIED_COLUMNS`.

- [ ] **Step 4: Implement `sync_methods_tried_projection.py`**

Implementation requirements:

- CLI args: `--repo-root`, `--pkg`.
- Read `methods_tried.csv`.
- Rewrite only the selected package object's top-level `methodsTried` field in `research_html/data/research-packages.js`.
- Preserve all other package fields and package order.
- Emit only the six compatibility fields consumed by dashboard JS.
- If no `methods_tried.csv` exists, leave existing legacy `methodsTried[]` untouched and exit `0`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_methods_tried_fact_projection.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add skills/research-package/scripts/append_methods_tried_fact.py skills/research-package/scripts/sync_methods_tried_projection.py tests/package_facts/test_methods_tried_fact_projection.py
git commit -m "Project methodsTried from CSV facts"
```

---

### Task 5: Research-Op Fact-Backed Inserts

**Files:**
- Modify: `skills/research-op/scripts/ops/insert.py`
- Modify: `skills/research-op/scripts/validate.py`
- Modify: `skills/research-op/scripts/transitions.py`
- Test: `tests/research-op/test_fact_backed_inserts.py`
- Extend: `tests/research-op/test_validate.py`

- [ ] **Step 1: Write failing tests**

Add tests for three cases:

1. `insert tracker-live-check-row` on a fact-backed package writes `live_checks.csv`, renders `tracker.html`, and records the files in `_actions.jsonl`.
2. `insert tracker-resource-allocation-row` on a fact-backed package writes `resource_allocation.csv`, renders `tracker.html`, and records the files in `_actions.jsonl`.
3. `insert methodsTried` with `source_ref=result_table_P1:current_best` writes `methods_tried.csv`, syncs `research-packages.js`, and records both files.

Define "fact-backed package" as: `research_html/data/packages/<pkg>/` exists.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/research-op/test_fact_backed_inserts.py tests/research-op/test_validate.py
```

Expected: insert handlers still mutate HTML or registry directly.

- [ ] **Step 3: Update validation**

In `validate.py`:

- allow optional `source_ref` on `methodsTried` insert payloads;
- if `source_ref` is present, require `method`, `hypothesis`, and `gate`;
- if `source_ref` is absent and `verdict=PASS`, reject for fact-backed packages with rule `manual-pass-forbidden`.

In `transitions.py`:

- keep existing target names so user-facing `research-op` commands do not change.

- [ ] **Step 4: Update insert handlers**

In `ops/insert.py`:

- add a helper `is_fact_backed(pkg)` that checks `research_html/data/packages/<pkg>/`;
- for fact-backed tracker targets, write CSV rows using `package_facts.upsert_csv_rows()` and then run `render_tracker_facts.py`;
- for fact-backed `methodsTried`, run `append_methods_tried_fact.py` and `sync_methods_tried_projection.py`;
- preserve current direct HTML/registry behavior for legacy packages without a fact directory.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/research-op/test_fact_backed_inserts.py tests/research-op/test_validate.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 5**

Run:

```bash
git add skills/research-op/scripts/ops/insert.py skills/research-op/scripts/validate.py skills/research-op/scripts/transitions.py tests/research-op/test_fact_backed_inserts.py tests/research-op/test_validate.py
git commit -m "Route fact-backed tracker and methods inserts through CSV"
```

---

### Task 6: Fix Checkpoint Fanout for Timely Tracker Updates

**Files:**
- Modify: `skills/research-op/scripts/events.py`
- Test: `tests/research-op/test_checkpoint_fanout.py`

- [ ] **Step 1: Write failing fanout tests**

Add a unit test that calls `events.fanout("CHECKPOINT_SAVED", ...)` with a fake dispatch function and asserts the operation sequence contains:

```python
[
    ("insert", "tracker-live-check-row"),
    ("insert", "tracker-resource-allocation-row"),
    ("insert", "results-gate-row"),
    ("update", "results-verdict"),
    ("update", "experiments-status"),
    ("update", "last-updated-time"),
    ("update", "last-updated-time"),
]
```

Also assert payload mapping keeps `exp_id` and artifact/measured fields.

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
python3 -m pytest -q tests/research-op/test_checkpoint_fanout.py
```

Expected: current fanout uses illegal `update` operations for tracker row targets.

- [ ] **Step 3: Update `CHECKPOINT_SAVED` fanout**

In `events.py`, change:

- `("update", "tracker-live-check-row", _cs_update_live_check)` to `("insert", "tracker-live-check-row", _cs_update_live_check)`
- `("update", "tracker-resource-allocation-row", _cs_update_allocation)` to `("insert", "tracker-resource-allocation-row", _cs_update_allocation)`

Do not change event names in this task.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/research-op/test_checkpoint_fanout.py tests/research-op/test_cli.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add skills/research-op/scripts/events.py tests/research-op/test_checkpoint_fanout.py
git commit -m "Fix checkpoint tracker fanout operations"
```

---

### Task 7: Extend Fact Alignment Lint to Tracker and Methods

**Files:**
- Modify: `skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py`
- Extend: `tests/research-dashboard/test_fact_alignment.py`

- [ ] **Step 1: Write failing lint tests**

Add tests that:

- pass when tracker `data-source-row="live_checks:P1:P1-r1"` resolves to `live_checks.csv`;
- fail with `fact-source-row-missing` when a tracker source row is absent;
- fail with `methods-projection-stale` when `research-packages.js methodsTried[]` differs from `methods_tried.csv`;
- warn with `fact-no-projection` for legacy packages that have no package fact directory.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/research-dashboard/test_fact_alignment.py
```

Expected: Phase 1 fact alignment only understands result projections.

- [ ] **Step 3: Implement tracker and methods checks**

Update `lint_fact_alignment()`:

- scan both `results.html` and `tracker.html`;
- resolve source refs against all CSV files in `research_html/data/packages/<pkg>/tables`;
- compare fact-backed package `methods_tried.csv` rows to the compatibility `methodsTried[]` array;
- treat missing tracker/method projections as errors only for packages with `research_html/data/packages/<pkg>/` present.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/research-dashboard/test_fact_alignment.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 7**

Run:

```bash
git add skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py tests/research-dashboard/test_fact_alignment.py
git commit -m "Lint tracker and methods fact projections"
```

---

### Task 8: Documentation and Integration Verification

**Files:**
- Modify: `skills/research-package/references/package-contract.md`
- Modify: `skills/research-exp-live/references/status-contract.md`
- Modify: `WORKFLOW.md`

- [ ] **Step 1: Document Phase 2 ownership**

Update docs with these rules:

- `live_checks.csv` is the canonical tracker live-check table for fact-backed packages.
- `resource_allocation.csv` is the canonical tracker allocation table for fact-backed packages.
- `methods_tried.csv` is the canonical methods table; `research-packages.js methodsTried[]` is a generated compatibility projection.
- `status.json` remains the live-run source; tracker CSV rows are extracted snapshots, not the raw runtime truth.
- Manual methods rows cannot support `PASS`.

- [ ] **Step 2: Run focused and regression tests**

Run:

```bash
python3 -m pytest -q \
  tests/package_facts \
  tests/exp_live/test_extract_tracker_facts.py \
  tests/research-dashboard/test_fact_alignment.py \
  tests/research-op/test_fact_backed_inserts.py \
  tests/research-op/test_checkpoint_fanout.py

python3 -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Inspect the final diff**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intended files are modified or untracked.

- [ ] **Step 4: Commit Task 8**

Run:

```bash
git add WORKFLOW.md skills/research-package/references/package-contract.md skills/research-exp-live/references/status-contract.md
git commit -m "Document tracker and methods fact ownership"
```

---

## Acceptance Criteria

1. A real `status.json` can generate tracker CSV rows without hand-editing `tracker.html`.
2. `tracker.html` live-check and resource-allocation rows are projections from CSV for fact-backed packages.
3. A `methodsTried` row can be generated from a source result row reference.
4. `research-packages.js methodsTried[]` is generated from `methods_tried.csv` for fact-backed packages.
5. `CHECKPOINT_SAVED` no longer fans out to illegal tracker update targets.
6. Lint detects stale tracker projections and stale methods compatibility projections.
7. Legacy packages remain readable and are not force-migrated.

## Out of Scope

- Full page projection revision enforcement. That is Phase 3.
- Removing legacy `methodsTried[]` consumers.
- Migrating every existing package.
- Inferring final experiment verdicts from live metrics.
