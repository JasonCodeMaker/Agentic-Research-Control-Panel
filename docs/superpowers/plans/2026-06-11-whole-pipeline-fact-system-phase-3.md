# Whole Pipeline Fact System Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce full projection discipline for fact-backed packages: repeated facts are rendered from JS/CSV sources, projections record source revisions, lint treats HTML as a projection instead of a source of truth, and fact-backed `research-op` events avoid partial writes.

**Architecture:** Keep the lightweight JS + CSV design. Store page projection metadata inside `<pkg>.facts.js` under `projections.pages`. Use existing CSV tables for table facts. Add one orchestration renderer that calls page renderers, records source revisions, and writes the HTML revision. Extend lint so fact-backed packages must have fresh page projection markers. Keep legacy packages in warning mode until explicitly migrated.

**Tech Stack:** Python 3.13 stdlib, existing `lib/package_facts`, existing Phase 1/2 renderers, existing `learnings_lint.py`, existing `research-op`, existing pytest suite.

---

## Preconditions

- Phase 1 is landed first.
- Phase 2 is landed first.
- Fact-backed packages are identified by `research_html/data/packages/<pkg>/`.
- Legacy packages without a package fact directory remain in compatibility mode.

## File Structure

- Modify `lib/package_facts/__init__.py`: add projection metadata helpers.
- Create `skills/research-package/scripts/render_package_projection.py`: orchestrate all page projections and update `<pkg>.facts.js`.
- Modify package templates: add stable projection markers to repeated-fact sections on `index.html`, `plan.html`, `tracker.html`, `results.html`, and `analysis.html`.
- Modify `skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py`: make fact alignment strict for fact-backed packages and prefer CSV/JS reads over HTML parsing.
- Create `skills/research-dashboard/assets/dashboard/scripts/audit_fact_migration.py`: classify packages as legacy, partial, or fact-backed.
- Create `skills/research-op/scripts/fact_transaction.py`: stage fact and projection writes before replacing live files.
- Modify fact-backed `research-op` insert/update handlers to use staged writes.
- Update docs in `WORKFLOW.md` and `skills/research-package/references/package-contract.md`.
- Add tests under `tests/package_facts/`, `tests/research-dashboard/`, `tests/research-package/`, and `tests/research-op/`.

---

### Task 1: Projection Metadata Helpers

**Files:**
- Modify: `lib/package_facts/__init__.py`
- Test: `tests/package_facts/test_projection_metadata.py`

- [ ] **Step 1: Write failing metadata tests**

Create tests for these helpers:

- `load_facts_js(pkg, root)` returns `{}` when the file is absent.
- `record_page_projection(pkg, "results.html", sources, html_path, renderer, root)` writes:

```python
{
    "projections": {
        "pages": {
            "results.html": {
                "renderer": "render_result_facts.py",
                "sources": {
                    "tables/result_table_P1.csv": "sha256:<digest>"
                },
                "htmlRevision": "sha256:<digest>",
                "renderedAt": "<iso timestamp>"
            }
        }
    }
}
```

- `assert_page_projection_fresh(pkg, "results.html", root)` passes when all source revisions and the HTML revision match current files.
- `assert_page_projection_fresh()` raises `FactError` when a CSV source changes after rendering.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_projection_metadata.py
```

Expected: projection helpers are missing.

- [ ] **Step 3: Implement helpers**

Add helpers to `lib/package_facts`:

- `is_fact_backed(pkg, root=Path(".")) -> bool`
- `relative_source_revision(pkg, source, root=Path(".")) -> str`
- `record_page_projection(pkg, page, sources, html_path, renderer, root=Path(".")) -> Path`
- `page_projection(pkg, page, root=Path(".")) -> dict`
- `assert_page_projection_fresh(pkg, page, root=Path(".")) -> None`

Rules:

- `sources` are relative to `research_html/data/packages/<pkg>/` when they start with `tables/`; otherwise they are repo-root relative.
- Existing facts fields are preserved when projection metadata is updated.
- Missing source files raise `FactError`.
- Projection metadata stays in `<pkg>.facts.js`; do not introduce a separate projection database.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_projection_metadata.py tests/package_facts/test_schema.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add lib/package_facts/__init__.py tests/package_facts/test_projection_metadata.py
git commit -m "Add package projection metadata helpers"
```

---

### Task 2: Unified Package Projection Renderer

**Files:**
- Create: `skills/research-package/scripts/render_package_projection.py`
- Test: `tests/package_facts/test_render_package_projection.py`

- [ ] **Step 1: Write failing orchestration tests**

Create tests that prepare a fact-backed package with:

- `results.html`
- `tracker.html`
- `result_table_P1.csv`
- `result_gate.csv`
- `live_checks.csv`
- `resource_allocation.csv`

Run:

```bash
python3 skills/research-package/scripts/render_package_projection.py \
  --repo-root "$TMP" \
  --pkg 2026-06-11-demo \
  --page all
```

Assertions:

- the script calls the result renderer and tracker renderer;
- `<pkg>.facts.js` contains projection entries for `results.html` and `tracker.html`;
- changing `live_checks.csv` makes `package_facts.assert_page_projection_fresh(pkg, "tracker.html")` fail until the renderer is run again;
- `--page results` updates only the results projection entry;
- unknown page exits `2`.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_render_package_projection.py
```

Expected: renderer script is missing.

- [ ] **Step 3: Implement orchestration renderer**

Create `render_package_projection.py`:

- CLI args: `--repo-root`, `--pkg`, `--page` with choices `all`, `results`, `tracker`.
- For `results`, run `render_result_facts.py`, then record page projection sources:
  - every `tables/result_gate.csv` file that exists;
  - every `tables/result_table_*.csv` file that exists.
- For `tracker`, run `render_tracker_facts.py`, then record page projection sources:
  - `tables/live_checks.csv` if it exists;
  - `tables/resource_allocation.csv` if it exists.
- Use `subprocess.run(..., check=True)` and return exit code `2` when a child renderer fails.
- Keep the script stdlib-only.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_render_package_projection.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add skills/research-package/scripts/render_package_projection.py tests/package_facts/test_render_package_projection.py
git commit -m "Add package projection renderer"
```

---

### Task 3: Projection Markers in New Package Templates

**Files:**
- Modify: `skills/research-package/templates/index.html`
- Modify: `skills/research-package/templates/plan.html`
- Modify: `skills/research-package/templates/tracker.html`
- Modify: `skills/research-package/templates/results.html`
- Modify: `skills/research-package/templates/analysis.html`
- Extend: `tests/research-package/test_create_research_package.py`

- [ ] **Step 1: Write failing scaffold tests**

Extend package scaffold tests to assert these markers exist in newly created packages:

- body has `data-package-id="<pkg>"`;
- repeated-fact sections have `data-fact-projection`:
  - `index.html`: `overview`
  - `plan.html`: `plan`
  - `tracker.html`: `tracker`
  - `results.html`: `results`
  - `analysis.html`: `analysis`
- no existing `data-table-body` selectors are renamed.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/research-package/test_create_research_package.py
```

Expected: some markers are absent.

- [ ] **Step 3: Add markers**

Update templates only by adding attributes to existing elements. Do not rewrite page content.

Required placements:

- `index.html`: add `data-fact-projection="overview"` to the primary overview section that displays package status and plan status.
- `plan.html`: add `data-fact-projection="plan"` to the pipeline timeline section.
- `tracker.html`: keep Phase 2 tracker/resource markers and add `data-fact-projection="tracker"` to the tracker user-zone wrapper.
- `results.html`: keep Phase 1 result markers and add `data-fact-projection="results"` to the result-blocks wrapper.
- `analysis.html`: add `data-fact-projection="analysis"` to the rules/insights container.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/research-package/test_create_research_package.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add skills/research-package/templates/index.html skills/research-package/templates/plan.html skills/research-package/templates/tracker.html skills/research-package/templates/results.html skills/research-package/templates/analysis.html tests/research-package/test_create_research_package.py
git commit -m "Mark package projection sections in templates"
```

---

### Task 4: Strict Projection Lint for Fact-Backed Packages

**Files:**
- Modify: `skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py`
- Extend: `tests/research-dashboard/test_fact_alignment.py`

- [ ] **Step 1: Write failing lint tests**

Add tests for:

- fact-backed package with fresh `results.html` and `tracker.html` projection metadata passes `fact-alignment --strict`;
- fact-backed package with changed CSV source fails with `projection-stale-source`;
- fact-backed package with changed HTML after rendering fails with `projection-stale-html`;
- fact-backed package missing `data-fact-projection` on a required page fails with `projection-marker-missing`;
- legacy package without `research_html/data/packages/<pkg>/` emits warnings, not errors.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/research-dashboard/test_fact_alignment.py
```

Expected: Phase 2 lint does not enforce page projection revisions.

- [ ] **Step 3: Implement strict projection lint**

Update `lint_fact_alignment()`:

- for fact-backed packages, require projection metadata for `results.html` when result CSVs exist;
- require projection metadata for `tracker.html` when live/resource CSVs exist;
- call `package_facts.assert_page_projection_fresh()` for each required page;
- scan page HTML for `data-fact-projection`;
- keep legacy packages warning-only unless `--strict` is passed and a package has a fact directory.

- [ ] **Step 4: Wire `all` mode**

Update `all` command dispatch so it includes `fact-alignment` after existing status/evidence/alignment checks.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/research-dashboard/test_fact_alignment.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py tests/research-dashboard/test_fact_alignment.py
git commit -m "Enforce fresh projections for fact-backed packages"
```

---

### Task 5: Prefer Facts Over HTML in Dashboard Lints

**Files:**
- Modify: `skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py`
- Test: `tests/research-dashboard/test_fact_source_read_paths.py`

- [ ] **Step 1: Write failing read-path tests**

Add tests for:

- `draft-method` reads `result_gate.csv` instead of parsing `results.html` when `result_gate.csv` exists.
- alignment result-row checks use `result_gate.csv` when present.
- evidence checks use `methods_tried.csv` when present and use `methodsTried[]` only for legacy packages.
- if CSV exists and HTML has a conflicting value, lint reports stale projection instead of accepting the HTML value.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/research-dashboard/test_fact_source_read_paths.py
```

Expected: current lint paths still parse HTML and registry arrays first.

- [ ] **Step 3: Add fact read helpers**

Inside `learnings_lint.py`, add helpers:

- `package_fact_tables(pid, repo_root=REPO_ROOT) -> dict[str, Path]`
- `result_gate_rows(pid, html_fallback=True) -> list[dict]`
- `methods_tried_rows(pid, registry_pkg, registry_fallback=True) -> list[dict]`

Rules:

- fact-backed packages read CSV first.
- legacy packages use current HTML/registry parsing.
- fact-backed packages do not silently fall back to HTML when CSV exists but is malformed.

- [ ] **Step 4: Refactor call sites**

Update:

- `draft_method`
- result-gate event scan
- alignment readiness result-row checks
- methods evidence checks

Keep existing output text stable unless a test intentionally checks a new fact-source violation.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/research-dashboard/test_fact_source_read_paths.py tests/research-dashboard/test_fact_alignment.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 5**

Run:

```bash
git add skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py tests/research-dashboard/test_fact_source_read_paths.py
git commit -m "Prefer package facts over HTML in dashboard lints"
```

---

### Task 6: Atomic Fact Transaction Helper

**Files:**
- Create: `skills/research-op/scripts/fact_transaction.py`
- Test: `tests/research-op/test_fact_transaction.py`

- [ ] **Step 1: Write failing transaction tests**

Create tests for:

- staging two file writes does not modify live files until `commit()` runs;
- `commit()` replaces all staged files with `os.replace`;
- validation failure before `commit()` leaves live files unchanged;
- a simulated write error leaves already existing live files unchanged and removes temp files.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/research-op/test_fact_transaction.py
```

Expected: helper is missing.

- [ ] **Step 3: Implement transaction helper**

Create `fact_transaction.py` with:

- `class FactTransaction`
- `stage_text(path: Path, text: str)`
- `stage_bytes(path: Path, data: bytes)`
- `commit()`
- `cleanup()`

Implementation rules:

- write temp files under the destination directory with suffix `.facttmp`;
- create parent directories before staging;
- validate all staged paths before commit;
- replace files only during `commit()`;
- call `cleanup()` in `finally` blocks from callers.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/research-op/test_fact_transaction.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add skills/research-op/scripts/fact_transaction.py tests/research-op/test_fact_transaction.py
git commit -m "Add atomic fact transaction helper"
```

---

### Task 7: Use Transactions in Fact-Backed Research-Op Writes

**Files:**
- Modify: `skills/research-op/scripts/ops/insert.py`
- Modify: `skills/research-op/scripts/ops/update.py`
- Modify: `skills/research-dashboard/assets/dashboard/scripts/propagate_apply.py`
- Test: `tests/research-op/test_fact_backed_atomicity.py`

- [ ] **Step 1: Write failing atomicity tests**

Add tests that simulate renderer failure after CSV staging:

- fact-backed `insert tracker-live-check-row` leaves `live_checks.csv` and `tracker.html` unchanged when rendering fails;
- fact-backed `insert methodsTried` leaves `methods_tried.csv` and `research-packages.js` unchanged when projection sync fails;
- `propagate_apply.py` does not mark a manifest applied when a fact-backed projection write fails.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/research-op/test_fact_backed_atomicity.py
```

Expected: current fact-backed writes are not staged as one transaction.

- [ ] **Step 3: Refactor fact-backed writes**

For fact-backed packages:

- compute CSV text in memory;
- compute rendered HTML text in memory or render to a staged temp path;
- stage all output files through `FactTransaction`;
- call `commit()` only after all validation and rendering succeeds;
- append `_actions.jsonl` only after commit succeeds.

Keep legacy direct mutation behavior unchanged in this task.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest -q tests/research-op/test_fact_backed_atomicity.py tests/research-op/test_fact_backed_inserts.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 7**

Run:

```bash
git add skills/research-op/scripts/ops/insert.py skills/research-op/scripts/ops/update.py skills/research-dashboard/assets/dashboard/scripts/propagate_apply.py tests/research-op/test_fact_backed_atomicity.py
git commit -m "Use transactions for fact-backed research-op writes"
```

---

### Task 8: Migration Audit and Documentation

**Files:**
- Create: `skills/research-dashboard/assets/dashboard/scripts/audit_fact_migration.py`
- Test: `tests/research-dashboard/test_audit_fact_migration.py`
- Modify: `WORKFLOW.md`
- Modify: `skills/research-package/references/package-contract.md`
- Modify: `skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py`

- [ ] **Step 1: Write failing audit tests**

Add tests for `audit_fact_migration.py`:

- package with no package fact directory is reported as `legacy`;
- package with result CSVs but no tracker CSVs is reported as `partial`;
- package with result, tracker, and methods CSVs plus fresh projections is reported as `fact-backed`;
- `--json` prints a stable machine-readable report.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/research-dashboard/test_audit_fact_migration.py
```

Expected: audit script is missing.

- [ ] **Step 3: Implement audit script**

Create `audit_fact_migration.py`:

- CLI args: `--repo-root`, optional `--pkg`, optional `--json`;
- read `research-packages.js` through the existing node dump helper;
- inspect `research_html/data/packages/<pkg>/tables`;
- use `package_facts.assert_page_projection_fresh()` for fact-backed page checks;
- report counts by `legacy`, `partial`, `fact-backed`, and `stale`.

- [ ] **Step 4: Document final ownership contract**

Update docs:

- HTML is a projection for fact-backed packages.
- JS facts own repeated prose-like content.
- CSV facts own repeated tables.
- `outputs/<pkg>/...` owns raw experiment evidence.
- `status.json` owns live run state.
- lint may parse HTML only for legacy packages.
- fact-backed direct HTML edits are rejected when they touch projected sections.

- [ ] **Step 5: Add lint note**

In `learnings_lint.py`, add a note to `fact-alignment` output summarizing the package's migration state from the audit helper.

- [ ] **Step 6: Run focused and full tests**

Run:

```bash
python3 -m pytest -q \
  tests/package_facts \
  tests/research-dashboard/test_fact_alignment.py \
  tests/research-dashboard/test_fact_source_read_paths.py \
  tests/research-dashboard/test_audit_fact_migration.py \
  tests/research-op/test_fact_transaction.py \
  tests/research-op/test_fact_backed_atomicity.py

python3 -m pytest -q
git diff --check
```

Expected: all tests pass and no whitespace errors.

- [ ] **Step 7: Commit Task 8**

Run:

```bash
git add WORKFLOW.md skills/research-package/references/package-contract.md skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py skills/research-dashboard/assets/dashboard/scripts/audit_fact_migration.py tests/research-dashboard/test_audit_fact_migration.py
git commit -m "Document and audit full fact projection discipline"
```

---

## Acceptance Criteria

1. Fact-backed packages record source revisions for projected pages.
2. Changing a source CSV or JS fact without rendering triggers lint failure.
3. Changing projected HTML without updating projection metadata triggers lint failure.
4. Dashboard lints read CSV/JS facts first for fact-backed packages.
5. HTML parsing remains only as a legacy fallback.
6. Fact-backed research-op writes stage all related file changes before commit.
7. A package migration audit can distinguish legacy, partial, fact-backed, and stale packages.

## Out of Scope

- Automatic migration of every old package.
- Replacing Scope SSOT files.
- Adding a database or service.
- Removing legacy HTML parsing before all existing packages are migrated.
