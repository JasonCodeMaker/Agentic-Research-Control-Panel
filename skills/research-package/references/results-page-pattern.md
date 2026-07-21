# Results page pattern

This document defines the recommended `results.html` body. It preserves the
existing human layout while changing the data source from page-owned facts to
Experiment run evidence.

Rendered pages live at:

```text
.research/interface/packages/<package-id>/results.html
```

The values displayed on that page come from:

```text
.research/experiments/<package-id>/<experiment-id>/<run-id>/result.json
```

The page is a human projection. It is never management or evidence authority.

## Choose the body shape

Use one of two existing shapes:

- **Per-Experiment cards:** use for about one to five discrete Experiments,
  each with one verdict. Keep one
  `<article data-card="exp-result" data-exp-id="...">` per Experiment.
- **Track tables:** use when many measurements group into evaluation tracks,
  repeated sweeps, seed studies, or ablations. Keep one
  `<article data-card="track-<slug>">` per track.

The choice changes body density, not the surrounding page layout.

## Section order

Preserve this order:

1. Masthead with title, lead, toolbar, status strip, and package navigation.
2. One hypothesis restatement.
3. Optional evaluation-contract banner.
4. Optional headline metric strip.
5. Result-gate table with one row per planned Experiment.
6. Per-Experiment cards or per-track tables.
7. Validity-class summary.
8. No-change affirmation when a transition is claimed.
9. Footer timestamp.

Existing sections, cards, tables, and `data-*` anchors remain stable.

## Result-gate scope

The result gate is a verdict table for planned Experiments such as `P0`,
`P1`, and `P2`.

- A sweep cell, seed, or ablation measurement belongs inside its owning result
  card or track table.
- An in-flight Experiment keeps a gate row with `unmeasured` values.
- A diagnostic-only Experiment keeps its row and displays its validity reason.
- If there are no planned Experiments, omit the result-gate section.

Every displayed gate outcome must cite the owning run result.

## Per-Experiment card

Each card should contain:

1. Experiment id and purpose.
2. Gate and current validity.
3. Observed metric with run id and evidence link.
4. Baseline and protocol-match verdict.
5. Supported and unsupported claims.
6. Optional inline figure with a caption.

Do not copy the same metric into an unrelated page-owned fact file.

## Track module

A track groups measurements that share one evaluation context. Inside each
track, keep:

1. A title naming the track and covered Experiment ids.
2. An optional policy subtitle.
3. A short paragraph naming the current checkpoint and evidence roots.
4. One visible canonical table.
5. A two-to-four item interpretation summary.
6. One inline figure when a curve is decision-relevant.
7. Closed `<details>` blocks for supplementary tables.

Supplementary blocks remain closed by default. The visible table carries the
canonical comparison.

Recommended collapse order:

1. Alternate model or checkpoint comparison.
2. Multi-seed cross-tab.
3. Hyperparameter ablation.
4. Superseded variant.
5. Diagnostic-only or out-of-budget evidence.

Diagnostic rows keep an explicit validity chip at row level.

## Headline metric strip

Use two to four cards:

- current best under the canonical policy;
- baseline under the same formula and policy;
- one or two supporting values that explain the decision.

Each value slot keeps a descriptive `data-field` name. The rendered card also
links to the source Experiment and run. Do not mix policies inside one
headline comparison.

Example:

```html
<section data-section="headline" id="headline" aria-label="Headline result">
  <article class="module-card" data-card="headline">
    <h2>Headline result</h2>
    <p class="card-text">Canonical comparison under the accepted policy.</p>
    <div class="metric-strip">
      <article class="metric-card module-card">
        <div class="k">Current best Recall@10</div>
        <div class="v" data-field="headline-new">unmeasured</div>
        <div class="card-text">Source Experiment and run are linked here.</div>
      </article>
      <article class="metric-card module-card">
        <div class="k">Baseline Recall@10</div>
        <div class="v" data-field="headline-baseline">unmeasured</div>
        <div class="card-text">Same dataset, protocol, and policy.</div>
      </article>
    </div>
  </article>
</section>
```

## Sortable tables

Tables with `class="data-table"` use the shared enhancer rendered at:

```text
.research/interface/assets/research.js
```

Do not add page-local sorting code. Use `data-sortable="false"` when body
cells use `rowspan` or `colspan`. Use `data-sort="off"` only for a column that
has no meaningful ordering.

## Validity discipline

Keep validity visible at row or card level:

- `ok`: canonical and valid;
- `partial`: only part of the accepted gate cleared;
- `unmeasured`: no admissible result yet; and
- `fail`: failed, superseded, diagnostic-only, or outside the accepted budget.

Do not aggregate these classes into one success count. The validity summary
reports separate counts.

## Evidence binding

A renderer may display a value only when the source run record provides:

- Package and Experiment identity;
- run id;
- metric name and value;
- gate result;
- validity;
- config reference;
- code revision;
- dataset and checkpoint references when applicable; and
- supporting artifact paths.

Missing provenance renders as `unmeasured` or diagnostic-only according to the
metric contract. It must not be reconstructed from prose.

## Keep out of the page

- repeated checkpoint paths in every table cell;
- full execution logs;
- long review transcripts;
- multiple hypothesis restatements;
- aggregates that mix evaluation policies;
- prose-only diagnostic labels;
- state that exists only in HTML; and
- instructions that tell an agent to read the rendered page as context.

## Layout preservation check

After a renderer rebuild, compare the generated page with the previous human
surface:

- same page and section hierarchy;
- same navigation and collapsed-detail behavior;
- same stable anchors;
- same table and card layout;
- updated `.research/` paths; and
- values traceable to Experiment evidence.

Only the data contract and path ownership change. The human layout and visual
design remain unchanged.
