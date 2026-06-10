# Whole Pipeline Fact System Design

Date: 2026-06-11
Status: Design approved for planning

## Problem

The current pipeline has strong mutation rules, but its facts are still stored
across several surfaces:

- `research_html/data/research-packages.js` stores package identity,
  `experiments[]`, status, route, and selected state fields.
- `outputs/<pkg>/runs/<run_id>/status.json` stores live run state.
- `outputs/<pkg>/manifests/*.json` triggers selected surface updates.
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
- introducing SQLite, a service, a database, or a new web app;
- retro-migrating every old package in one pass;
- auto-inventing metrics that are not present in experiment artifacts.

## Architecture

The fact system adds one package data layer under `research_html/data/packages/`:

```text
outputs/<pkg>/...
  runs/<run_id>/status.json
  runs/<run_id>/events.jsonl
  manifests/*.json
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

Authority order:

1. Runtime artifacts under `outputs/<pkg>/...` are the raw experimental
   evidence.
2. Extractors convert raw evidence into package CSV tables.
3. `<pkg>.facts.js` stores non-table package facts and projection metadata.
4. CSV files store all table facts.
5. HTML pages render JS and CSV facts; they do not own repeated values.
6. Lint checks that HTML projections are fresh and source-backed.

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
      headlineFact: "result_table_P1:current_best",
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
  }
};
```

Rules:

- JS content facts own prose-like values that are repeatedly displayed.
- JS content facts may reference CSV rows by `<table_id>:<row_id>`.
- JS content facts do not store metric grids or result tables.
- `research-packages.js` remains the dashboard registry and package-card index,
  but package-page content facts move into `<pkg>.facts.js`.

## Table Facts

CSV is the canonical format for package tables. Every table row must have a
stable row id and enough provenance to verify where the row came from.

Minimum columns for result-like tables:

```csv
row_id,exp_id,metric,value,unit,split,baseline,verdict,validity,source_artifact,source_mtime,extractor,extracted_at
```

Additional columns are allowed when the table needs them, such as `dataset`,
`seed`, `checkpoint`, `setting`, `budget`, `candidate_cap`, `notes`, or
`source_type`.

Required conventions:

- `row_id` is the repeat-display anchor. Headline cards, result gate cells,
  result tables, and methods-tried projections all refer to the same row id.
- `source_artifact` points to the raw runtime artifact or committed evidence
  file.
- `source_mtime` records the artifact timestamp used during extraction.
- `extractor` records the script or adapter that produced the row.
- `extracted_at` records when the CSV row was generated.
- `validity` uses the shared result-validity enum.
- `verdict` uses the shared experiment-verdict enum when the row is a verdict
  row; otherwise it is empty or `INCONCLUSIVE`.

Manual rows are allowed only as explicit exceptions:

```csv
row_id,exp_id,metric,value,source_type,source_note,verified_by,validity,verdict
manual_p1,P1,Recall@1,42.1,manual,"copied from reviewer-supplied sheet",uqzzha35,PARTIAL,INCONCLUSIVE
```

Manual rows cannot produce `PASS` by default. A later implementation may allow a
PASS only after an explicit user-ack slot and artifact-backed verification rule.

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
  "output_csv": "research_html/data/packages/<pkg>/tables/result_table_P1.csv",
  "generated_at": "2026-06-11T10:00:00+10:00"
}
```

Rules:

- Extractors must fail closed when an input is missing or malformed.
- Extractors must not infer absent metrics.
- Extractors must preserve enough provenance for a reviewer to trace every
  displayed number to a raw artifact.
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
- tracker ledgers render from CSV or from live-run `status.json` snapshots;
- hand-written table values in HTML are forbidden for new result sections.

Projected HTML should carry source markers:

```html
<section data-source="tables/result_table_P1.csv" data-fact-revision="sha256:...">
```

When a page renders a single row repeatedly, it should carry the row source:

```html
<span data-source-row="result_table_P1:current_best">42.1</span>
```

The renderer owns these markers. Agents should not hand-author them except in
tests or migration fixtures.

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

The long-term composite event contract should be transactional at the fact
layer:

- validate all inputs first;
- compute all output file changes in memory;
- write fact files and projections only after validation passes;
- mark manifest applied only after all writes succeed.

This avoids the current partial-write failure mode where one surface can be
updated before another surface rejects.

## Validation

Add a `fact-alignment` lint mode. It should check:

- every projected table section has a `data-source`;
- every `data-source` file exists;
- every `data-source-row` resolves to a real CSV row;
- repeated displays of the same value reference the same row id;
- projected revision matches current JS/CSV revision;
- no new result number appears only in HTML;
- manual rows are labelled and cannot silently support PASS;
- package `experiments[]` status agrees with result CSV verdict state;
- enum casing is normalized at the fact layer.

The stop gate should require:

- `fact-alignment` passes for any touched package;
- extractor manifests exist for generated result CSVs;
- no unapplied event manifest can change package facts;
- no stale projection remains after fact changes.

## Migration Plan

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

`methodsTried[]` in `research-packages.js` becomes a derived compatibility view
or is replaced by renderer output after downstream consumers are updated.

### Phase 3: Full Projection Discipline

All package pages declare `data-source` and `data-fact-revision` for repeated
facts. Lint stops parsing HTML as a source of truth and instead verifies HTML as
a projection.

## Error Handling

- Missing extractor input: fail extraction; do not write CSV.
- Malformed CSV: reject projection; keep previous HTML unchanged.
- Stale projection: lint error for touched packages, warning for grandfathered
  untouched packages.
- Manual PASS attempt: reject unless a future explicit ack rule allows it.
- Partial propagation failure: leave manifest unapplied and report the failed
  target; do not mark facts or projections fresh.

## Testing

Focused tests should cover:

- extractor converts a fixture runtime artifact into CSV with provenance columns;
- renderer builds a result table from CSV and source markers;
- headline and result gate both reference the same row id;
- changing a CSV value without rendering triggers stale projection lint;
- manually editing an HTML result number triggers fact-alignment failure;
- manual rows cannot yield PASS;
- existing alignment tests still pass for task-spine structure;
- old packages without fact files are warnings unless touched structurally.

## Non-Goals

- No database.
- No server-side dashboard.
- No mandatory global migration in one commit.
- No generic extractor framework before package-specific extractors prove
  repeated patterns.
- No weakening of the existing mutation rule or Scope SSOT boundary.

## Acceptance Criteria

1. A new package can define result facts with one JS file and CSV tables.
2. A result table can be generated from a real artifact through an extractor.
3. `results.html` can be regenerated from JS/CSV without hand-written numbers.
4. Headline, result gate, and detailed result table can point to the same
   `row_id`.
5. Lint can detect stale or hand-written result projections.
6. Existing packages remain readable while new result edits use the fact layer.
7. The implementation plan starts with Phase 1 and leaves Phase 2/3 as follow-up
   work unless the user explicitly expands scope.
