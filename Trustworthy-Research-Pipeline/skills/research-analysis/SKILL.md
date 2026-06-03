---
name: research-analysis
description: "Create, maintain, and validate the per-package `analysis.html` page (Rules + Insight). Use this skill whenever the user types /research-analysis, asks to initialize / scaffold / lint an analysis page, asks to add a distilled rule or a deep-analysis insight to a package, asks to summarize an insight into a rule, or asks to embed a visualization (bar chart, heatmap, threshold chart, admission matrix) into an insight sub-block. Project-agnostic. Hard requirement: the dashboard at <cwd>/research_html/ must already exist (run /research-dashboard first) and the target package must already exist (run /research-package first). Analysis is the single home for the lessons distilled from a package's results — Rules are generalized constraints future packages must obey; Insights are the mechanism-level diagnostics that justify those rules. Both blocks are manual-only and never auto-populated from results, tracker, or inventory."
argument-hint: "<subcommand: init | add-insight | add-rule | lint> [args]"
allowed-tools: Bash(*), Read, Edit, Write, Glob, Grep
---

# Research Analysis

## Purpose

Own the per-package `analysis.html` page so its contract stays invariant across packages. The page captures the deep analysis of a package's results — the *why* behind the verdicts on `results.html` (Insight block) — and the generalizable design lessons future packages must obey (Rules block). The skill provides four crisp operations: init, add-insight, add-rule, lint.

## Authority

Authority order, highest first:
1. The user's invocation prompt and any explicit `--<flag>` overrides.
2. Trust rules `T1–T24` in `<root>/rules/trustworthy-research-rules.html`.
3. Form rules `R1–R18` in `<root>/rules/html-rules.html`.
4. The two-block contract in this skill (below).
5. [references/viz-templates.md](references/viz-templates.md) — reusable visualization snippets with the canonical color palette.

## Boundary (binding)

- `results.html` owns *what happened* — result-gate table, validity chips, per-experiment cards, claim analysis. Mechanically populated; inventory-coupled; lint-gated.
- `analysis.html` owns *why it happened* (Insight) and *what future packages must not repeat* (Rules). **Hand-curated only. No auto-population. No propagate_facts hook. No `methodsTried` writes.**
- Rules in `analysis.html` are **NOT** `methodsTried[]` in `data/research-packages.js`. `methodsTried` is a per-experiment verdict record consumed by `learnings.html`. Rules are generalized, transferable design constraints consumed by humans+agents to avoid repeating mistakes. The two co-exist and answer different questions.
- Stage order on the package nav: `overview → plan → implementation → results → analysis → tracker → docs`. Analysis sits between `results` and `tracker` (the chosen-route / next-action decision is folded into `tracker.html#chosen-route`).
- File writes to `analysis.html` (and removals) go through `/research-op insert --target analysis-rule` / `--target analysis-insight`; the footer `<time>` timestamp is bumped automatically by the insert handler, so no separate call is needed. This skill owns the **editorial decision** (when a rule is warranted, what counts as an insight); `/research-op` owns the **file format** (where to insert, what shape, lint compliance). Lint (`scripts/lint_analysis.py`) stays in this skill.

## Pre-flight checks

1. The dashboard exists:
   ```bash
   test -f <cwd>/research_html/index.html && test -f <cwd>/research_html/data/research-packages.js && echo dashboard-ok
   ```
2. The target package exists:
   ```bash
   test -f <cwd>/research_html/packages/<id>/index.html && echo package-ok
   ```
3. The dashboard JS registers `analysis` in `STAGE_PAGES` (`<root>/assets/research.js`) and the CSS holds the per-page override (`body[data-page="analysis"] #rules { grid-template-columns: 1fr; }`). The dashboard skill ships both — if either is missing, the dashboard is out of date; ask the user to re-run `/research-dashboard` rather than patching the dashboard from this skill.

If any check fails, stop and tell the user what to run first; do not silently scaffold the prerequisite.

## Two-block contract (binding)

`analysis.html` carries exactly two top-level sections, in this order:

1. **Rules** (`<section id="rules" data-section="rules">`) — a numbered list, one `<li>` per rule.
2. **Insight** (`<section id="insight" data-section="insight">`) — a stack of collapsible `<details>` sub-blocks, one per analyzed experiment, phase, or theme.

The rules block sits above the insight block because rules are the high-density take-away; the insight block is the supporting evidence.

### Rules block — strict format

- Container: `<ol class="rules-list" data-list="rules">`.
- Each rule is one `<li class="card-text" id="rule-<slug>">…</li>`.
- The slug is kebab-case and unique within the page (e.g. `rule-non-binding-precondition`).
- Body is plain natural-language prose, written so a human reader and an agent both understand and can apply the rule **without** re-opening the linked insight. Embed the binding numbers, thresholds, and named subjects inline.
- **No `<strong>`, `<b>`, or other emphasis on the rule itself.** Plain sentences, not imperatives in bold.
- **Exactly one evidence link**, placed as the final clause: `Evidence: <a href="#insight-<slug>">…</a>.`
- Add a rule **only when a result clearly warrants a generalizable lesson, not on every run**. The Rules block can stay empty for the whole life of a package.

When the page is initialized and no rule exists yet, render a placeholder:

```html
<li class="card-text"><em>No rules recorded yet.</em></li>
```

Remove the placeholder when the first real rule lands.

### Insight block — strict format

- Container: `<div class="insight-body" data-block="insight-body">`.
- Each insight is a `<details class="insight-subblock" id="insight-<slug>">` card. **Always `<details>` (closed); never `<details open>`.**
- The `<summary>` is the clickable title bar (one line, no nested elements).
- The `<details>` body is a single inner `<div>` with consistent padding; inside it: narrative paragraphs (`<p class="card-text">`), optional `<h4>` sub-headings, inline-styled visualizations from [references/viz-templates.md](references/viz-templates.md), and one caption paragraph immediately after each visualization.
- Every visualization caption is a `<p class="card-text" style="font-size:0.88rem; color:#555;">` paragraph that starts with `<em>Reading:</em>` and explains what the reader should take away.
- **Closed by default (binding):** every insight sub-block renders closed. The summary line is the index; readers click to expand. This rule supersedes any earlier guidance that said the most recent insight should be `<details open>`.
- Each sub-block has a stable deep-link anchor (`id="insight-<slug>"`) so rules can cite it.
- **Manual update only.** Never auto-populate an insight from `results.html`, `tracker.html`, or `data/research-packages.js`.

When the page is initialized and no insight exists yet, render a placeholder:

```html
<p class="card-text"><em>No insight content yet.</em></p>
```

Remove the placeholder when the first real insight lands.

## Visualization palette (binding)

Visualizations are **inline-styled HTML/CSS only** — no external charting libraries, no `<script>` blocks, no canvas. Use the colors below. Every visualization is followed by exactly one caption paragraph.

| Role | Color | Notes |
| --- | --- | --- |
| Card chrome (`<details>` border) | `#d8dde6` | 1 px solid |
| Card chrome (`<details>` background) | `#fafbfd` | very light off-white |
| Card chrome (`<summary>` text) | `#1f2a44` | dark navy |
| Bar background | `#eef` | very light blue-gray |
| Bar border | `#ccd` | 1 px solid |
| Neutral / baseline bar fill | `#888` | medium gray |
| Pass / improved bar fill | `#4a8e63` | medium green |
| Fail / regressed bar fill | `#a14444` | medium red |
| Threshold dashed line | `#c33` | 2 px dashed |
| Pass chip bg / text / border | `#dff5e3` / `#0a5d24` / `#b8e5c2` | green chip |
| Fail chip bg / text / border | `#fde2e2` / `#7a1a1a` / `#f0b8b8` | red chip |
| Heatmap gradient (best → worst) | `#fbe0db → #f4ada1 → #e89486 → #c8593f → #a93527 → #8c2c1f → #691f15` | seven discrete bands |
| Caption | `font-size:0.88rem; color:#555;` | always after a viz |

See [references/viz-templates.md](references/viz-templates.md) for copy-paste-ready snippets of:

- threshold bar chart (one row per cell, vertical threshold line)
- before/after paired bar table (rowspan delta column)
- 2-D heatmap (e.g. `G × p` dose-response)
- single-axis dose-response bar chart (e.g. sibling-count tax)
- admission matrix (2-D pass/drop grid)

## Operations

The skill has four subcommands. All are explicitly user-triggered; none run on a timer or as part of a fact-propagation cycle.

### `init <package-id>`

Install the empty `analysis.html` page in the package and opt it into the package's inventory `pages` array.

```bash
python <skill-dir>/scripts/init_analysis_page.py \
  --root <cwd>/research_html \
  --package-id <YYYY-MM-DD-slug>
```

Behavior:

- Reads the package's existing `name` from `data/research-packages.js`.
- Writes `<root>/packages/<id>/analysis.html` from `templates/analysis.html` (refuses to overwrite unless `--force`).
- Adds `"analysis"` to the package's `pages` array in `data/research-packages.js` if not already present.
- Verifies (does not patch) that the dashboard ships:
  - `analysis` in `STAGE_PAGES` (in `<root>/assets/research.js`)
  - `body[data-page="analysis"] #rules { grid-template-columns: 1fr; }` in `<root>/assets/research.css`
  - Both ship from the `research-dashboard` skill — emit a warning with the patch command if absent.
- After init, every subsequent edit to `analysis.html` goes through `/research-op insert --target analysis-rule|analysis-insight` (this skill's `add-rule` and `add-insight` subcommands are thin wrappers around those).

### `add-insight <package-id> <slug> <title>`

Append one new `<details>` sub-block to the Insight block. The agent then hand-edits the body. This skill delegates the file write to `/research-op`:

```bash
python skills/research-op/scripts/research_op.py \
  --pkg <package-id> --op insert --target analysis-insight \
  --payload '{"slug":"<slug>","title":"<title>","body":"<body html>"}'
```

`/research-op` writes the `<details class="insight-subblock" id="insight-<slug>">` wrapper closed by default; the agent edits the inner body via `Edit` after the wrapper lands. Use `templates/insight-subblock.html` as the shape reference for that body. This skill no longer ships its own scaffolding script for insight additions.

**Embed a visualization** (the `embed a bar chart / heatmap / …` trigger): after the insight wrapper lands, open the matching snippet in [references/viz-templates.md](references/viz-templates.md) — threshold bar chart, paired before/after bar, 2-D heatmap, single-axis dose-response, or admission matrix — paste it into the insight body via `Edit`, recolor with the [palette](#visualization-palette-binding), and add the required `<em>Reading:</em>` caption paragraph immediately after it. No separate subcommand or script is involved.

This insert is only legal while the package `category` is `in-progress`; for terminal packages (`success` / `fail`) the analysis page is frozen and `/research-op` rejects the call — surface the rejection and ask the user before attempting a write.

### `add-rule <package-id> <slug> <evidence-slug>`

Append one new numbered `<li>` to the Rules block. The agent hand-crafts the prose; this skill delegates the file write to `/research-op`:

```bash
python skills/research-op/scripts/research_op.py \
  --pkg <package-id> --op insert --target analysis-rule \
  --payload '{"slug":"<slug>","evidence_slug":"<evidence-slug>","prose":"<rule prose>"}'
```

`/research-op` runs the analysis-rule Phase 2 rules (slug kebab-case, no bold on rule body) and either writes or rejects with the structured envelope; the single-Evidence-link constraint is enforced by `lint` (below), not at write time. Use `templates/rule-bullet.html` as the shape reference. This skill no longer ships its own scaffolding script for rule additions.

For the **summarize-an-insight-into-a-rule** trigger: first read the target insight sub-block, distill the single generalizable lesson, then call `add-rule` with that prose and the insight's slug as `<evidence-slug>` so the rule's Evidence link resolves. There is no separate `summarize` subcommand — it is `add-rule` applied to an existing insight.

As with `add-insight`, this insert is only legal while the package `category` is `in-progress`; for terminal packages (`success` / `fail`) `/research-op` rejects the call — surface the rejection and ask the user before attempting a write.

### `lint <package-id-or-all>`

Validate the contract on one package or all packages. Returns non-zero on violations.

```bash
python <skill-dir>/scripts/lint_analysis.py \
  --root <cwd>/research_html \
  [--package-id <id> | --all]
```

Checks per page:

- `<body data-page="analysis" data-package-id="<id>">` is present and the id matches the directory.
- The two sections appear in order: `#rules` first, then `#insight`. No other top-level section between them.
- Every `<li>` inside `<ol class="rules-list">` either is the `No rules recorded yet.` placeholder OR has `id="rule-<slug>"` with a kebab-case slug and contains exactly one `Evidence: <a href="#insight-<slug>">…</a>` link.
- Every `<li class="card-text" id="rule-*">` body contains no `<strong>` or `<b>` tag wrapping the rule itself (inline `<em>` for emphasis on a sub-clause is allowed; the lint checks only `<strong>`/`<b>`, not `<em>`).
- Every `<details>` inside `<div class="insight-body">` has `id="insight-<slug>"`, exactly one `<summary>`, and at least one `<p class="card-text">` in its body.
- Every visualization (any element with `style="…background:#…"` that contains `width:` or sits inside a grid) is followed by a caption `<p class="card-text" style="…0.88rem…color:#555…">`.
- Every `#rule-*` Evidence link resolves to an `#insight-*` anchor that exists on the same page.
- Inventory check: the package's `pages` array in `data/research-packages.js` includes `"analysis"`.
- Dashboard check: `STAGE_PAGES` in `<root>/assets/research.js` includes the `analysis` slot, and the `#rules` CSS override is present.

A clean lint exits 0 silently; violations are printed one per line with a file:line anchor where possible.

## Update cadence (binding)

- **Insight** is updated **only on explicit user instruction**. If a user says "summarize the V0 results into an insight," that's an explicit instruction. If the agent is on a propagate_facts cycle, it never touches `analysis.html`.
- **Rules** are updated only when a result clearly warrants a generalizable lesson. Most experiments will not warrant a new rule. An insight without a rule is still useful; a rule without an insight to link is not allowed.
- When a rule is added, the linked insight must already exist on the page (the `lint` subcommand catches broken `#insight-<slug>` links).

## Relationship to other skills

- `/research-dashboard` ships the global JS/CSS that registers the analysis page in the nav and fixes the 1-column layout for the Rules section. Re-run it after pulling the dashboard skill if either piece is missing.
- `/research-package` scaffolds the package shell. When `--scope` includes `analysis` (or is `all`), the scaffolder writes an empty `analysis.html` and adds `analysis` to the inventory `pages` array. The `research-analysis` skill then owns content updates on the page from that point on.
- `learnings.html` and `data/research-packages.js` `methodsTried[]` are owned by `/research-package`. Rules in `analysis.html` are a separate plane and never feed `learnings.html`.

## Final response

After any subcommand, state:

- subcommand and arguments
- package id
- files written / patched
- inventory updates
- lint result (if applicable)
- one-line "next action" suggestion (e.g. "Add the first rule with `/research-analysis add-rule …`")

Apply the dashboard's output-classification rule: agent-only continuity notes go in a `>` blockquote.

## Bundled resources

- `templates/analysis.html` — empty two-block scaffold rendered by `init`.
- `templates/insight-subblock.html` — one collapsible insight card, copy-paste boilerplate.
- `templates/rule-bullet.html` — one numbered rule `<li>`, copy-paste boilerplate.
- `references/viz-templates.md` — five visualization patterns with the canonical color palette.
- `scripts/init_analysis_page.py` — init subcommand implementation.
- `scripts/lint_analysis.py` — lint subcommand implementation.
