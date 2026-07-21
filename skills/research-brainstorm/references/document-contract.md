# Brainstorm document contract

Use this contract when creating or materially restructuring a Brainstorm. The
shared Dashboard renderer owns the outer page and its visual system. Author
only the research-specific body fragment.

## Stable shell

Every generated Brainstorm page contains:

1. lifecycle metadata and navigation;
2. Title;
3. Abstract / TLDR;
4. Idea Snapshot;
5. a Table of Content derived from `h2` and `h3` headings;
6. a free-form document body;
7. revision and authority provenance.

The stable shell is a navigation and reading contract, not a research schema.
Do not require empty Problem, Method, Metric, Risk, or References sections.

## State-backed inputs

- `title`: required document title.
- `abstract`: concise TLDR. Fall back to the original `idea` for legacy rows.
- `idea_snapshot`: optional string, mapping, or ordered list of
  `{label, value}` rows. Labels are chosen for the current idea.
- `document_note`: a content-addressed `text/html` body fragment.
- `idea`, `rough_metric`, and `lit_refs`: backward-compatible summary and
  grounding fields. They are not mandatory document sections.

The renderer derives status, revision, timestamps, archive notice, and ToC.
Do not store a second manually maintained ToC in state.

## Body freedom

Use semantic HTML. The body may contain any meaningful combination of:

- `section`, `h2`, and `h3`;
- paragraphs, ordered or unordered lists;
- responsive tables with captions and scoped headers;
- figures, diagrams, and `figcaption`;
- formulas, code, paths, and citations;
- callouts, decision gates, open questions, and stage flows.

Figures and tables are capabilities, not quotas. Add them when they make a
relationship easier to inspect. Do not add decorative images or empty sections.

## Fragment boundary

The body file is an HTML fragment. It must not contain:

- `doctype`, `html`, `head`, or `body` elements;
- `script`, `style`, `link`, `iframe`, or embedded executable content;
- a second page header, navigation shell, ToC, or footer;
- copied Dashboard CSS.

Keep every heading text meaningful because the renderer uses it for the ToC.
Use unique explicit IDs when stable deep links matter.

## Reusable classes

The shared `brainstorm.css` supports these optional primitives:

| Class | Purpose |
| --- | --- |
| `doc-section` | Standard readable Section |
| `wide` | Allows a Section to use the full article width |
| `section-number` | Small visual Section index inside an `h2` |
| `doc-callout` | Important note or boundary |
| `neutral` | Neutral callout variant |
| `table-wrap` and `doc-table` | Responsive research table |
| `research-figure` | Bordered figure with caption |
| `stage-flow` and `flow-step` | Three or more dependent stages |
| `metric-grid` and `metric-cell` | Repeated metric definitions |
| `decision-list` and `decision-row` | Decision gates or interpretations |
| `source-list` | Grounding and provenance list |

These classes are presentational helpers. Plain semantic HTML remains valid.

## Example fragment

```html
<section class="doc-section" id="core-question">
  <h2><span class="section-number">01 </span><span>Core question</span></h2>
  <p>State the observable research question and its claim boundary.</p>
  <div class="doc-callout">
    <strong>Open assumption</strong>
    <p>Name what must be verified before promotion.</p>
  </div>
</section>

<section class="doc-section wide" id="comparison">
  <h2><span class="section-number">02 </span><span>Comparison design</span></h2>
  <div class="table-wrap">
    <table class="doc-table">
      <caption>Cost-matched alternatives</caption>
      <thead>
        <tr><th scope="col">Arm</th><th scope="col">Difference</th></tr>
      </thead>
      <tbody>
        <tr><td>Control</td><td>No query update</td></tr>
        <tr><td>Draft method</td><td>Candidate-conditioned update</td></tr>
      </tbody>
    </table>
  </div>
</section>
```

## Reading and accessibility

- Keep ordinary prose within the renderer's reading column.
- Use the wide variant only for tables, figures, or dense comparisons.
- Give tables captions and header scopes.
- Give image figures useful alt text and captions.
- Preserve visible keyboard focus and logical heading order.
- Do not encode meaning by color alone.
- Avoid motion unless it communicates a state transition.

## Archive and merge behavior

An archived page keeps the same document structure. It adds an Archived marker,
the archive reason, and a link to the canonical Brainstorm when `merged_into`
is present. Finalize subordinate content before the archive event because
archived research content is immutable.
