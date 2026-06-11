# Whole Pipeline Fact System Design

Date: 2026-06-11
Status: Revised design; ready for Phase 1 planning after Phase 0 preconditions

## Problem

The current pipeline has strong mutation rules, but its facts are still stored
across several surfaces:

- `research_html/data/research-packages.js` stores package identity,
  `experiments[]`, status, route, and selected state fields.
- `outputs/<pkg>/runs/<run_id>/status.json` stores live run state.
- `outputs/<pkg>/manifests/*` and scanner-detected runtime artifacts trigger
  selected surface updates.
- `results.html` and `tracker.html` store many table values directly in HTML.
- `methodsTried[]` stores finalized experiment measurements as strings.
- lint tools parse HTML tables to recover facts that should already be typed.

This creates misalignment because the same fact can be copied into multiple
places. A page can become stale without a clear source-of-truth violation, and
an agent can accidentally update one display while leaving another display
behind.

The target is a lightweight whole-pipeline fact system:

- no database;
- no heavy event-sourcing rewrite;
- JavaScript remains the content-data format;
- CSV becomes the table-data format;
- experiment result tables are generated from real experiment artifacts whenever
  possible.

## Scope

This design covers the whole pipeline boundary, but it lands incrementally.
The first implementation plan should start with result tables, because they are
the most common source of duplicated values and unsupported claims.

In scope:

- the protocol change that moves result-table ownership from repeated HTML cells
  to typed package facts;
- canonical content facts for package pages;
- canonical CSV tables for result gates, result tables, live checks, resource
  allocation, and methods tried;
- extraction from runtime artifacts into CSV;
- HTML projection from JS and CSV;
- validation that duplicated displays reference the same source row;
- stop-gate checks for stale or hand-written projections.

Out of scope:

- replacing `outputs/_scope/transitions.jsonl` as the Scope SSOT;
- replacing `outputs/<pkg>/runs/<run_id>/status.json` as live-run truth;
- making `analysis.html` rules or insights auto-generated; they remain
  hand-curated research-analysis artifacts;
- introducing SQLite, a service, a database, or a new web app;
- retro-migrating every old package in one pass;
- auto-inventing metrics that are not present in experiment artifacts.

## Protocol Boundary

This design applies to target research projects after the pipeline is attached.
The toolbox repo implements the templates, renderers, validators, and
`research-op` targets that create and maintain the data layer; it does not need a
top-level `research_html/` directory of its own.

Existing protocol files must be updated in the same implementation branch that
lands Phase 1:

- `AGENTS.md` must describe the new authority order for fact-layer packages.
- `WORKFLOW.md` must route result recording through fact writes and projection
  rendering, not direct HTML table edits.
- `research-op` references and legality targets must distinguish legacy HTML
  targets from fact-layer targets.

Until those protocol updates land, the current contract remains in force:
`results.html` / `tracker.html` are still the operational recording surfaces.
After Phase 1 lands for a package, result table values in those pages are
projections and the CSV/JS fact files are the package-page source of truth.

## Architecture

The fact system adds one package data layer under `research_html/data/packages/`:

```text
outputs/<pkg>/...
  runs/<run_id>/status.json
  runs/<run_id>/events.jsonl
  manifests/*
  _actions.jsonl

research_html/data/packages/
  <pkg>.facts.js
  <pkg>/
    tables/
      result_gate.csv
      result_table_<exp_id>.csv
      live_checks.csv
      resource_allocation.csv
      methods_tried.csv
    extractors/
      <exp_id>.json

research_html/packages/<pkg>/
  index.html
  plan.html
  tracker.html
  results.html
  analysis.html
  docs/
```

Authority order for packages that have opted into the fact layer:

1. Scope remains the intent authority and is still stored in
   `outputs/_scope/transitions.jsonl`.
2. Package `plan.html` remains the executable plan and gate-definition surface.
3. Runtime artifacts under `outputs/<pkg>/...` are the raw experimental
   evidence.
4. Extractors convert raw evidence into package CSV tables.
5. CSV files own package-page table facts, including measurements, validity
   labels, result-gate rows, and methods-tried rows.
6. `<pkg>.facts.js` owns repeated non-table package-page facts, row aliases, and
   projection metadata.
7. `research-packages.js` remains the dashboard registry, package-card index, and
   compatibility surface for consumers not yet migrated to CSV facts.
8. HTML pages render JS and CSV facts; they do not own repeated result values.
9. Lint checks that HTML projections are fresh and source-backed.

`research-op` remains the mutation gate for package surfaces. Its targets should
gradually move from "edit HTML cell" to "write package fact", "write package
table row", "render projection", and "check fact alignment".

## Content Facts

`<pkg>.facts.js` stores non-table facts:

```js
window.PACKAGE_FACTS = window.PACKAGE_FACTS || {};
window.PACKAGE_FACTS["<pkg>"] = {
  schemaVersion: 1,
  packageId: "<pkg>",
  updatedAt: "2026-06-11",
  sourceScopeNode: "dir/example",
  objective: {
    hypothesis: "...",
    metric: "...",
    baseline: "...",
    successPredicate: "..."
  },
  pages: {
    results: {
      headlineFact: "result_table_P1:p1_best_seed42",
      headlineAlias: "current_best",
      summary: "..."
    },
    tracker: {
      currentState: "RESULT_ANALYSIS",
      nextRoute: "RUN_NEXT_EXPERIMENT",
      blocker: ""
    }
  },
  projections: {
    resultsHtmlRevision: "sha256:...",
    trackerHtmlRevision: "sha256:..."
  },
  rowAliases: {
    "result_table_P1:current_best": "result_table_P1:p1_best_seed42"
  }
};
```

Rules:

- JS content facts own prose-like values that are repeatedly displayed.
- JS content facts may reference CSV rows by `<table_id>:<row_id>`.
- JS content facts do not store metric grids or result tables.
- Dynamic names such as `current_best` are aliases stored in JS facts. They must
  resolve to immutable CSV row ids; the target row stays unchanged when the alias
  later points somewhere else.
- `research-packages.js` remains the dashboard registry and package-card index,
  but package-page content facts move into `<pkg>.facts.js`. Compatibility
  fields may remain there until all consumers are migrated.

## Table Facts

CSV is the canonical format for package tables. Every table row must have a
stable row id and enough provenance to verify where the row came from.

Minimum columns for result-like tables:

```csv
row_id,exp_id,metric,value,unit,split,baseline,verdict,validity,source_type,source_artifact,source_mtime,source_size,source_sha256,extractor,extracted_at
```

Additional columns are allowed when the table needs them, such as `dataset`,
`seed`, `checkpoint`, `setting`, `budget`, `candidate_cap`, `row_role`, or
`notes`.

Required conventions:

- `row_id` is immutable within a table. It is the repeat-display anchor for
  headline cards, result gate cells, result tables, and methods-tried
  projections.
- `exp_id` is not a row id. One experiment can have many rows for seeds,
  checkpoints, datasets, budgets, summary rows, or diagnostics.
- `source_artifact` points to the raw runtime artifact or committed evidence
  file.
- `source_mtime` records the artifact timestamp used during extraction.
- `source_size` and `source_sha256` record the source bytes used during
  extraction. `source_mtime` is advisory and never sufficient by itself.
- `extractor` records the script or adapter that produced the row.
- `extracted_at` records when the CSV row was generated.
- `validity` uses the shared result-validity enum.
- `verdict` uses the shared experiment-verdict enum when the row is a verdict
  row; otherwise it is empty or `INCONCLUSIVE`.

Canonical enum values are stored in SCREAMING_SNAKE:

```text
EXPERIMENT_VERDICT = PASS | FAIL | INCONCLUSIVE | DIAGNOSTIC
RESULT_VALIDITY = VALID | PARTIAL | RESULT_FAIL | UNMEASURED | DIAGNOSTIC_ONLY | MISSING
```

Renderers may map these values to legacy lowercase HTML chip values, but CSV and
JS facts must use the canonical values above.

Manual rows are allowed only as explicit exceptions:

```csv
row_id,exp_id,metric,value,source_type,source_artifact,source_note,verified_by,validity,verdict
manual_p1,P1,Recall@1,42.1,manual,evidence/reviewer_sheet.csv,"copied from reviewer-supplied sheet",uqzzha35,PARTIAL,INCONCLUSIVE
```

Manual rows must still point to a committed evidence artifact. They cannot
produce `PASS` by default. A later implementation may allow a PASS only after an
explicit user-ack slot and artifact-backed verification rule.

## Extractors

Experiment-related result tables should be generated directly from real
experiment outputs.

Extractor input examples:

- `outputs/<pkg>/runs/<run_id>/status.json`;
- `outputs/<pkg>/runs/<run_id>/events.jsonl`;
- trainer logs;
- evaluation summary JSON;
- existing experiment CSV files;
- checkpoint manifests;
- candidate summary files.

Each extractor writes a manifest under
`research_html/data/packages/<pkg>/extractors/<exp_id>.json`:

```json
{
  "exp_id": "P1",
  "inputs": [
    "outputs/<pkg>/runs/<run_id>/status.json",
    "outputs/<pkg>/runs/<run_id>/summary.json"
  ],
  "extractor": "scripts/extract_result_table.py",
  "extractor_version": "sha256:<extractor-source-or-adapter-id>",
  "output_csv": "research_html/data/packages/<pkg>/tables/result_table_P1.csv",
  "output_sha256": "sha256:<csv-bytes>",
  "generated_at": "2026-06-11T10:00:00+10:00"
}
```

Rules:

- Extractors must fail closed when an input is missing or malformed.
- Extractors must not infer absent metrics.
- Extractors must preserve enough provenance for a reviewer to trace every
  displayed number to a raw artifact.
- Extractor code can live in the installed skill, the toolbox template, or the
  target project, but the manifest must record the adapter identity and version
  used for the row.
- Extractors may be package-specific at first; common extractors can be added
  after repeated patterns appear.

## Projection Flow

The approved data flow is:

```text
real experiment artifacts
  -> extractor
  -> package CSV/JS facts
  -> projection renderer
  -> HTML pages
  -> lint verifies projection freshness
```

HTML projection rules:

- result tables in `results.html` render from CSV;
- headline cards render from JS facts that reference CSV row ids;
- validity counts render from CSV validity values;
- methods-tried views render from finalized CSV rows;
- tracker live-check and resource-allocation ledgers render from CSV decision
  rows;
- tracker current-run widgets may show the latest `status.json` snapshot, but
  `status.json` is raw live state rather than the decision ledger;
- hand-written table values in HTML are forbidden for new result sections.

Projected HTML should carry source markers:

```html
<section data-source="tables/result_table_P1.csv" data-fact-revision="sha256:...">
```

When a page renders a single row repeatedly, it should carry the row source:

```html
<span data-source-row="result_table_P1:p1_best_seed42" data-source-alias="current_best">42.1</span>
```

The renderer owns these markers. Agents should not hand-author them except in
tests or migration fixtures.

`data-fact-revision` is the SHA-256 of a deterministic projection input bundle:
the normalized bytes of every CSV/JS fact file used by the rendered section,
the extractor manifest ids referenced by those rows, and the renderer id. The
lint tool must compute the same bundle hash; timestamps alone never prove
freshness.

## Propagation

Existing manifests and `research-op --event` paths should shift from directly
editing HTML to updating facts:

```text
artifact event
  -> validate raw artifact exists
  -> run or select extractor
  -> update CSV/JS facts
  -> render affected projections
  -> write one audit entry
```

The composite event contract must become transactional at the fact layer before
Phase 1 writes are accepted:

- validate all inputs first;
- compute all output file changes in memory;
- write each file through a temp path plus atomic rename, or snapshot changed
  files and roll them back on failure;
- write fact files and projections only after validation passes;
- mark the manifest applied, or advance the propagation cursor, only after all
  writes succeed.

This avoids the current partial-write failure mode where one surface can be
updated before another surface rejects.

## Validation

Add a `fact-alignment` lint mode. It should check:

- every projected table section has a `data-source`;
- every `data-source` file exists;
- every `data-source-row` resolves to a real CSV row;
- every `data-source-alias` resolves to an immutable row id in `<pkg>.facts.js`;
- repeated displays of the same value reference the same row id;
- projected revision matches current JS/CSV revision;
- no new result number appears only in HTML;
- manual rows are labelled and cannot silently support PASS;
- package `experiments[]` status agrees with result CSV verdict state;
- enum casing is normalized at the fact layer;
- source artifacts still match recorded `source_size` and `source_sha256`;
- `methodsTried[]` compatibility rows, when present, match
  `methods_tried.csv`;
- `analysis.html` rules and insights are ignored by projection freshness checks
  unless a future research-analysis design explicitly opts them in.

The stop gate should require:

- `fact-alignment` passes for any touched package;
- extractor manifests exist for generated result CSVs;
- no unapplied event manifest can change package facts;
- no stale projection remains after fact changes.

## Migration Plan

### Phase 0: Protocol and Infrastructure Preconditions

Before result facts become authoritative for any package:

- update `AGENTS.md`, `WORKFLOW.md`, `research-op` references, and package
  contracts so agents know CSV/JS facts own fact-layer result values;
- add canonical enum constants and a single HTML-chip mapping;
- add the immutable row-id plus alias contract;
- add a deterministic projection-revision hash helper;
- add transactional fact writes with rollback or atomic temp-file replacement;
- add target-project directory creation for `research_html/data/packages/`;
- keep existing direct HTML `research-op` targets marked as legacy paths for
  packages that have not opted into the fact layer.

### Phase 1: Result Tables First

Add package facts and CSV result tables for `results.html`:

- `result_gate.csv`;
- `result_table_<exp_id>.csv`;
- facts.js headline and result summary references;
- renderer for result sections;
- lint that forbids new hand-written result numbers.

Existing packages are grandfathered. New or touched result sections must use the
fact layer.

### Phase 2: Tracker and Methods Tried

Move tracker and learnings-adjacent tables into CSV:

- `live_checks.csv`;
- `resource_allocation.csv`;
- `methods_tried.csv`.

`methodsTried[]` in `research-packages.js` remains required until dashboard,
learnings, context-pack, and lint consumers read `methods_tried.csv` directly.
During the compatibility window it is generated from `methods_tried.csv` and
kept byte-for-byte aligned by lint. It is removed or downgraded only after those
downstream consumers are updated.

### Phase 3: Full Projection Discipline

All package pages declare `data-source` and `data-fact-revision` for repeated
facts. Lint stops parsing HTML as a source of truth and instead verifies HTML as
a projection.

## Error Handling

- Missing extractor input: fail extraction; do not write CSV.
- Malformed CSV: reject projection; keep previous HTML unchanged.
- Source hash mismatch: reject extraction or projection until the artifact is
  re-read and the row provenance is regenerated.
- Broken row alias: reject projection; aliases must resolve before rendering.
- Stale projection: lint error for touched packages, warning for grandfathered
  untouched packages.
- Manual PASS attempt: reject unless a future explicit ack rule allows it.
- Partial propagation failure: rollback changed files or leave temp files
  unapplied, leave the manifest/cursor unapplied, and report the failed target;
  do not mark facts or projections fresh.

## Testing

Focused tests should cover:

- Phase 0 protocol checks identify fact-layer packages and legacy packages;
- extractor converts a fixture runtime artifact into CSV with provenance columns;
- source digest mismatch rejects extraction or projection;
- renderer builds a result table from CSV and source markers;
- headline and result gate both reference the same row id;
- `current_best` resolves through a JS alias to an immutable row id;
- changing a CSV value without rendering triggers stale projection lint;
- manually editing an HTML result number triggers fact-alignment failure;
- a failed multi-file propagation rolls back changed fact/projection files;
- manual rows cannot yield PASS;
- canonical enum values map to legacy HTML chips without changing CSV casing;
- generated `methodsTried[]` rows match `methods_tried.csv`;
- tracker live-check CSV rows stay distinct from raw `status.json` snapshots;
- existing alignment tests still pass for task-spine structure;
- old packages without fact files are warnings unless touched structurally.

## Non-Goals

- No database.
- No server-side dashboard.
- No mandatory global migration in one commit.
- No generic extractor framework before package-specific extractors prove
  repeated patterns.
- No weakening of the existing mutation rule or Scope SSOT boundary.
- No automatic generation of research-analysis rules or insights.

## Acceptance Criteria

1. Phase 0 protocol and infrastructure preconditions are implemented before any
   package treats CSV/JS facts as authoritative.
2. A target project can create `research_html/data/packages/<pkg>/` without the
   toolbox repo needing its own top-level `research_html/`.
3. A new package can define result facts with one JS file and CSV tables.
4. A result table can be generated from a real artifact through an extractor.
5. Every extracted row records source path, mtime, size, SHA-256, extractor id,
   and extraction time.
6. `results.html` can be regenerated from JS/CSV without hand-written numbers.
7. Headline, result gate, and detailed result table can point to the same
   immutable `row_id`; dynamic aliases resolve through `<pkg>.facts.js`.
8. Lint can detect stale projections, hand-written result numbers, broken
   aliases, enum casing drift, and source digest mismatch.
9. A failed multi-file propagation does not leave partially fresh facts or
   projections.
10. Existing packages remain readable while new result edits use the fact layer
    only after opting in.
11. The implementation plan starts with Phase 0 and Phase 1. Phase 2/3 remain
    follow-up work unless the user explicitly expands scope.
