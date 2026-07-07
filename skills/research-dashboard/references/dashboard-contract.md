# Dashboard Contract

The dashboard is the global research-system surface. Keep it project-agnostic.
Put project-specific goals in `window.RESEARCH_PROJECT_PROFILE`.

Required root files:

- `index.html`
- `assets/research.css`
- `assets/research.js`
- `data/research-packages.js`
- `data/rules.js` (the unified rules registry — see ownership note below)
- `categories/brainstorm/index.html`
- `categories/in-progress/index.html`
- `categories/success/index.html`
- `categories/fail/index.html`
- `package-template.html`

Required data globals:

- `window.RESEARCH_PROJECT_PROFILE`
- `window.RESEARCH_CATEGORIES`
- `window.RESEARCH_TAG_ROLES`
- `window.RESEARCH_PACKAGES`
- `window.RESEARCH_RULES` (in `data/rules.js`)

`data/rules.js` ownership (three populations, one schema): rows with
`origin="mirror"` are a write-locked projection of the shipped R/T rule files
(rebuilt by `ensure_dashboard.py`); rows with `origin="selfevolve"` are a
projection of the self-evolve Rule Store (rebuilt by `lib/context_pack`);
all other rows (project / package rules) are mutated only through
`research-op --target rule`. `learnings_lint.py lint-rules` checks schema,
id uniqueness, and both mirror syncs.

The chrome owns no protocol content: the objective panel renders from the
Scope SSOT projection (`data/scope-projection.js`), the routes panel from
`schema.js` (`NEXT_ROUTE` + `NEXT_ROUTE_MEANING`), and the rules section from
`data/rules.js`. `RESEARCH_GLOBAL_CONTEXT` / `RESEARCH_GLOBAL_PROTOCOL` are
retired — do not reintroduce protocol prose as chrome data.

Every package object must include:

- `id`
- `name`
- `category`
- `tag`
- `tagMeaning`
- `sourcePath`
- `runtime`
- `detailPath`
- `problem`
- `objective`
- `motivation`

Category-scoped tag meanings:

- `brainstorm`: the optimization direction
- `in-progress`: the current workflow status
- `success`: the adopted model, method, or pipeline part
- `fail`: the core failure reason

Dashboard pages should remain concise. Long plans, results, commands, and run
logs belong in package modules or artifact roots.

Required dashboard sections (each must carry the matching `data-section` anchor):

- `masthead`: title, lead paragraph, and toolbar with global dashboard links.
- `nav`: in-page anchor nav over the remaining sections.
- `snapshot`: one `data-card="dashboard-role"` article that names this surface
  as overview + agent context, and points readers to package surfaces for
  claims and evidence.
- `lanes`: the four lane summary cells produced by `renderDashboardSummary()`.
- `packages`: the full package grid populated by `renderPackages()`.
- `protocol`: the panels populated by `renderGlobalContext()` — objective
  (Scope SSOT projection, with an empty-state pointing at `/research-onboard`),
  allowed routes (schema.js), protocol link cards (workflow.ts / CLAUDE.md /
  rule files), and the tag legend. No protocol prose is stored here.
- `profile`: a `#project-profile-root` slot for project-specific specialization.
- `rules`: a section-level `Rule Registry` heading and lead, matching the
  `packages` section format, followed by the `#rules-registry-root` slot
  rendered from `data/rules.js` by `renderRulesRegistry()`. The registry
  groups universal rows by rule kind (`form`, `trust`) and uses the same
  grouped/empty-state component for future project and package rule rows.

Lane pages mirror the same chrome contract: the masthead carries
`data-section="masthead"`, the package grid carries `data-section="lane"`,
and the toolbar links both rule files.

Rule alignment: dashboard chrome satisfies R1, R6, R8, R9, R11, R13, and R18
from `rules/html-rules.html`. The trust rules (T1-T24) in
`rules/trustworthy-research-rules.html` apply to package surfaces, not to the
dashboard.

## Output classification (mirrored from SKILL.md)

The full rule lives in `SKILL.md` under [Output classification](../SKILL.md).
One-line summary for agents reading this contract first:

- **Agent-important only** chat output &rarr; wrap in a markdown `>`
  blockquote (UI collapses by default).
- **Agent-important only** HTML content &rarr; wrap in
  `<details data-audience="agent"><summary>agent context</summary>...</details>`
  (browser collapses by default).
- **Both-audience** content (the common case) renders inline without any
  wrapper.

`data-audience="agent"` extends the R6 stable-anchor taxonomy &mdash; agents
can grep for it to recover their private notes. Form rule R18 in
`rules/html-rules.html` is the binding HTML form of this rule.
