# Results Page Pattern (recommended structure)

This is a **recommended layout** for `results.html`, not a binding scaffold (R13 stays in force: skills scaffold, content stays free-form). The binding parts come from elsewhere — T23 (result-gate row shape when present), T8 (hypothesis restated), T10/R16 (per-validity counts, never aggregated), T16 (no-change affirmation on transitions), T11/T13 (baseline + checkpoint + git-commit pinned at the metric), R3 (visualizations inline), and the single-home rule in [package-contract.md](package-contract.md). Everything in this file is the layout pattern observed working well at scale; deviate when the package shape calls for it.

The canonical worked example is `research_html/packages/2026-05-11-panda-scaleup-zeroshot-scalability/results.html`. When this doc and the worked example disagree, the worked example is what the pattern was distilled from — update this doc rather than the package.

## When to use which body structure

The template ships with a per-experiment-card body. The Track-table body is an alternative for richer packages. Pick one:

- **Per-experiment cards** (template default) — when the package has a small number of discrete experiments (≈1–5), each producing one verdict. Each experiment gets one `<article data-card="exp-result" data-exp-id="…" data-validity="…">` with an observed-metric kv-grid, supported/unsupported claims cards, a protocol-match verdict, and an inline SVG plot. Result-gate rows correspond 1:1 to experiment cards. Good for plan / spec / pilot-grade packages.
- **Track tables** — when the package has many measurements that group into logical tracks (in-distribution vs zero-shot vs scalability sweep, or one dataset's ablation grid, or one codebook-width sweep across multiple datasets). Each track gets one `<article data-card="track-<slug>">` with a canonical main table and `<details>`-collapsed sub-tables for ablations / multi-seed / superseded / diagnostic-only data. Result-gate rows summarize at the planned-experiment level (P0, P1, …); track tables carry the per-measurement detail.

Choose Track tables when (a) the package has more than ~6 measurements, (b) measurements group naturally into 2+ tracks, or (c) the same comparison repeats across many cells (datasets × settings × seeds × ablations). The rest of this doc focuses on the Track-table variant since the per-experiment-card variant is already covered by the template.

## Section ordering (top to bottom)

1. **Masthead** (binding) — title, lead, toolbar, status-strip, package-nav.
2. **Hypothesis re-stated** (binding, T8) — exactly one `<p data-hypothesis-restated>` element, string-equal to plan.html canonical. Grep check at validation: exactly 1 match.
3. **Eval banner** (optional, recommended when canonical-policy distinction exists) — `<section data-section="eval-banner">` naming the canonical eval policy (BARS-on vs noBARS, compact-budget gate, beam width convention, etc.) and labelling which numbers are diagnostic-only. Omit when the package has a single eval policy with no diagnostic-only variants.
4. **Headline result** (optional, recommended for in-progress / success packages with a current-best to show) — `<section data-section="headline">` with a `<div class="metric-strip">` of 2–4 `<article class="metric-card module-card">` cards comparing current best vs baseline on the package's primary metric. See "Headline metric-strip pattern" below.
5. **Result gate** (T23, conditional) — `<section data-section="result-gate">` with the 10-column gate table. **Rows correspond to planned experiments in plan.html#experiments-list** (P0, P1, …), NOT to every measurement. Sweep cells, multi-seed validations, and ablation cells belong in per-track tables. See "Result-gate scope clarification" below.
6. **Per-track tables** (optional, the heart of this pattern) — `<section data-section="tracks">` containing one or more `<article data-card="track-<slug>">` modules. See "Track module pattern" below.
7. **Validity-class summary** (binding, T10/R16) — `<section data-section="validity-summary">` with the four chips (`valid`, `diagnostic_only`, `failed`, `missing`); never aggregated across classes.
8. **No-change affirmation** (binding when claiming a transition, T16) — boolean + commit hash + link to `implementation.html#owned-files`. Inside the validity-summary section is a fine home. Omit only when no transition is being claimed (rare for results.html).
9. **Footer** (binding) — `<time data-field="last-updated">`.

## Track module pattern

A "Track" groups related measurements that share one context (in-distribution Setting 1, zero-shot Settings 1+2, scalability sweep, one dataset's full ablation, etc.). One `<article data-card="track-<slug>">` per track, all wrapped in a single `<section data-section="tracks">`.

Inside one track module, the order is:

1. **`<h2>` track title** naming the track and the planned experiments it covers (e.g. "Track 1 — Panda in-distribution Setting 1 (P1, P2)").
2. **Optional `<h3>` policy sub-title** when the track has a canonical policy (e.g. "BARS-on (canonical: gamma=0.50, cap=300) — head-to-head with best new ckpt").
3. **One short intro paragraph** stating which ckpt is the current-best for this track, the comparison axis, and the source paths/anchors for the numbers below. Keep ckpt paths and JSON paths here, not duplicated in every row.
4. **One main canonical table** — `<table class="data-table" data-table="track-<slug>">` carrying the BARS-on / canonical-policy numbers for current-best vs baseline. Bold the current-best column. Add per-row `<small>(Δ vs baseline)</small>` annotations where useful. This is the table the reader sees by default.
5. **One bullet summary** after the main table — `<ul class="card-text">` with 2–4 bullets giving 4-dataset means, key wins, and compact-budget notes. The bullet summary distils what the table shows; it does not list every row.
6. **One inline figure** when the track has a curve (R3) — `<figure>` with inline SVG or committed PNG + `<figcaption>` + optional `<a href="*.pdf">` PDF link. Place after the main table when the curve IS the headline visualization (e.g. scalability trajectory).
7. **Collapse hierarchy of `<details>` blocks** for everything else. See below.

### Collapse hierarchy inside one track

Use nested `<details>` blocks for supplementary tables, in this priority order from top to bottom:

| Order | Variant | Default state | Summary text pattern |
|---|---|---|---|
| 1 | Current-best comparison (when it's the dominant decision axis, e.g. codebook-width head-to-head) | `<details open>` | `<b>Codebook-size comparison (c=512 / c=1024 / c=2048, …) — current vs prior best</b>` |
| 2 | Multi-seed cross-tab of the same comparison | `<details>` (closed) | `<b>c=1024 multi-seed cross-tab (s42, s220, s3407)</b> — click to expand` |
| 3 | Beam / hyperparameter ablation | `<details>` (closed) | `<b>Beam-width ablation (S1 beam=150, S2 beam=250) on best ckpt</b> — click to expand` |
| 4 | Superseded prior variant kept for provenance | `<details>` (closed) | `<b>old c=512 1.65M trajectory (superseded by c=1024)</b> — click to expand` |
| 5 | Diagnostic-only / outside-compact-budget / noBARS | `<details>` (closed) | `<b>GRDR-noBARS (diagnostic_only, superseded)</b> — click to expand` |

Inside each `<details>` block: one intro `<p class="card-text">` naming what the block contains + ckpt sources, then one `<table class="data-table" data-table="track-<slug>-<variant>">`, then optional bullet summary.

For diagnostic-only blocks, each row in the table must carry a `<span class="chip" data-validity="fail">diagnostic_only</span>` (or equivalent) chip per R16 — class distinction must be visible at the row level, not only in the prose label.

## Headline metric-strip pattern

When present, the headline is 2–4 cards on a `<div class="metric-strip">`:

```html
<section data-section="headline" id="headline" aria-label="Headline result">
  <article class="module-card" data-card="headline">
    <h2>Headline result</h2>
    <p class="card-text">Headline = arithmetic mean of <code>&lt;metric&gt;</code> across &lt;datasets&gt; under &lt;setting&gt;, &lt;ckpt-scope&gt;, &lt;policy-line&gt;. Current best = <b>&lt;variant&gt;</b> (&lt;single-seed/multi-seed status&gt;).</p>
    <div class="metric-strip">
      <article class="metric-card module-card">
        <div class="k">Headline mean &lt;metric&gt; (current best)</div>
        <div class="v" data-field="headline-new">…</div>
        <div class="card-text">mean(per-dataset values); &Delta; vs baseline; per-dataset wins summary</div>
      </article>
      <article class="metric-card module-card">
        <div class="k">Headline mean &lt;metric&gt; (baseline)</div>
        <div class="v" data-field="headline-baseline">…</div>
        <div class="card-text">mean(per-dataset values); policy + protocol line</div>
      </article>
      <!-- 1-2 more supporting cards (e.g. anchor-dataset single-number, scalability Δ, compact-pool note) -->
    </div>
  </article>
</section>
```

Card content rules:

- **Card 1**: current-best metric on the package's primary headline aggregation (often a 4-dataset mean, sometimes a single anchor metric).
- **Card 2**: baseline metric, same formula, same policy. If the package uses a canonical BARS-on policy, the baseline card uses BARS-on numbers too — do not mix policies across the two cards.
- **Cards 3–4**: supporting metrics that make the comparison interpretable (per-anchor-dataset single value, scalability Δ at the gate thresholds, gate-status summary, compact-budget note). Avoid stuffing more than 4 cards — split into a second `<div class="metric-strip">` or move detail into a track table if more breadth is needed.

Each card carries `<div class="k">` (label), `<div class="v" data-field="<slot>">` (value, the stable anchor for prompted edits), and `<div class="card-text">` (one-line breakdown). The `data-field` slot is the stable agent anchor — keep slot names descriptive of the position, not the value (e.g. `headline-new` not `c2048-canhit`).

## Eval banner pattern

When the package has a canonical-policy distinction:

```html
<section data-section="eval-banner" aria-label="Eval contract">
  <article class="module-card" data-card="eval-banner">
    <h2>Eval contract</h2>
    <p class="card-text">Canonical &lt;system&gt; policy is <b>&lt;policy-name-on&gt;</b>: <code>&lt;flag-line&gt;</code> (per &lt;link-to-source-package&gt;). All result tables below report &lt;policy-name-on&gt; numbers only. Earlier &lt;variant&gt; / &lt;policy-name-off&gt; runs are kept under collapsible blocks for provenance and are <span class="chip" data-validity="fail">diagnostic_only</span>.</p>
  </article>
</section>
```

The banner pins (a) which policy is canonical, (b) what flag-line implements it, (c) where the policy was decided (link to source package or design doc), (d) what older numbers are kept and how they are labelled. Omit the entire section when the package has only one eval policy and no diagnostic-only variants.

## Result-gate scope clarification

The result-gate is the verdict-level table for **planned experiments** (the rows in `plan.html#experiments-list`, named P0, P1, …). One gate row per planned experiment.

- A measurement that is a sweep cell, a multi-seed validation, or an ablation cell does **not** get its own gate row. It lives in a track table.
- A planned experiment that is still in flight gets a gate row with `unmeasured` cells and validity `pending`. Do not omit — omission is reserved for measurements that were never part of the plan.
- A planned experiment that became diagnostic-only after the fact still gets a gate row, with the diagnostic-only chip and reason cited.

If the package has no `plan.html#experiments-list` yet (rare; brainstorm or pre-plan packages), omit the entire result-gate section. The validity-summary section still runs from whatever validity chips appear in track tables.

## Concision via collapse, not via cutting columns

Track tables have no column-count cap. Concision comes from collapsing supplementary data under `<details>`, not from cutting columns from the main canonical table. Pick the column set that fully describes the canonical comparison; do not omit a metric to fit a width. If the canonical table becomes wide:

- Move supporting metrics into a second `<details>` block (e.g. multi-seed cross-tab) instead of trimming the main table.
- Add `<small>(Δ vs baseline)</small>` annotations inside cells so the eye does not need to scroll to a side-by-side baseline column.
- Wrap long ckpt paths in `<code>` and use `…` truncation in display only when the full path appears once in the track intro paragraph.

If a track grows past ~30 rows or ~3 ablation sub-tables, R8 kicks in: split into `packages/<id>/docs/<slug>.html` and link the track module to the doc page rather than piling on.

## Validity / chip discipline (R16, T10)

Inside any table that mixes canonical and diagnostic rows, each row carries a `<span class="chip" data-validity="…">` chip. Chip values in use: `ok` (canonical / valid), `partial` (gate cleared on some seeds / cells), `unmeasured` (in flight), `fail` (diagnostic-only / outside compact budget / superseded). Aggregated counts across these classes are forbidden in prose — keep the chips visible at the row level so the reader can count by class.

The validity-summary section at the bottom of the page reports the totals as four separate chips, never as one aggregate number.

## What NOT to bake into the page

- **Per-row checkpoint paths in every track table cell** — declare the ckpt once in the track intro paragraph and once per variant when a `<details>` block compares variants. Re-listing the same ckpt path in every row violates the single-home rule for ckpt anchors and bloats diffs.
- **Long verbatim review-loop transcripts or full round-by-round review summaries** — distil the actionable conclusions into `plan.html`, the lessons into `analysis.html`, and the important judgments into `tracker.html`. `results.html` carries verdicts and observed numbers only.
- **Multiple hypothesis re-statements** — exactly one `<p data-hypothesis-restated>` is required (T8 grep check). Do not restate the hypothesis inside the headline lead or eval banner.
- **Multi-track aggregate metrics that mix policies** — never average a BARS-on number with a noBARS number into one headline figure. Each metric-strip card sticks to one policy.
- **Prose-only labels for diagnostic-only data** — always pair the prose label with a `data-validity="fail"` chip at the row level (R16).

## Skeleton (Track-table body)

A minimal skeleton to copy into a new results.html, in addition to the binding sections from the template:

```html
<section data-section="eval-banner" aria-label="Eval contract">
  <article class="module-card" data-card="eval-banner">
    <h2>Eval contract</h2>
    <p class="card-text">Canonical policy is <b>…</b>: <code>…</code>. All result tables below report canonical numbers only. Diagnostic-only variants are collapsed below and labelled.</p>
  </article>
</section>

<section data-section="headline" id="headline" aria-label="Headline result">
  <article class="module-card" data-card="headline">
    <h2>Headline result</h2>
    <p class="card-text">Headline = … . Current best = <b>…</b> ( … ).</p>
    <div class="metric-strip">
      <article class="metric-card module-card">
        <div class="k">…</div>
        <div class="v" data-field="headline-new">unmeasured</div>
        <div class="card-text">…</div>
      </article>
      <article class="metric-card module-card">
        <div class="k">…</div>
        <div class="v" data-field="headline-baseline">unmeasured</div>
        <div class="card-text">…</div>
      </article>
    </div>
  </article>
</section>

<section data-section="tracks" id="tracks" aria-label="Track-by-track results">

  <article class="module-card" data-card="track-<slug>">
    <h2>Track N — <track name> (P<n>, P<m>)</h2>
    <h3>Canonical policy — head-to-head with best ckpt</h3>
    <p class="card-text">Best ckpt for this track = <b>…</b>. Source: <code>…</code>. &Delta; in parentheses = current best &minus; baseline.</p>
    <table class="data-table" data-table="track-<slug>-main">
      <thead><tr><th>…</th></tr></thead>
      <tbody>
        <tr><td>…</td></tr>
      </tbody>
    </table>
    <ul class="card-text">
      <li><b>4-dataset mean &Delta;:</b> …</li>
      <li><b>Compact-budget note:</b> …</li>
    </ul>

    <details open>
      <summary><b>Codebook-size comparison (current vs prior best)</b></summary>
      <p class="card-text">…</p>
      <table class="data-table" data-table="track-<slug>-codebook">…</table>
    </details>

    <details>
      <summary><b>Multi-seed cross-tab</b> — click to expand</summary>
      <p class="card-text">…</p>
      <table class="data-table" data-table="track-<slug>-multiseed">…</table>
    </details>

    <details>
      <summary><b>Ablation sweep</b> — click to expand</summary>
      …
    </details>

    <details>
      <summary><b>Superseded prior variant</b> — click to expand</summary>
      …
    </details>

    <details>
      <summary><b>Diagnostic-only (noBARS / over compact budget)</b> — click to expand</summary>
      …
    </details>
  </article>

</section>
```

## Maintenance triggers

The skill's description includes results.html maintenance triggers (edit / update / extend / restructure / headline / Track / ablation / collapse). When the user invokes any of these, follow this pattern; deviate explicitly when the package shape calls for it, and update the pattern doc when a new variant proves itself across multiple packages.
