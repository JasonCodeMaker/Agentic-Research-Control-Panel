# Dashboard Contract

The dashboard is the global research-system surface. Keep it project-agnostic.
Put project-specific goals in `window.RESEARCH_PROJECT_PROFILE`.

Required root files:

- `index.html`
- `assets/research.css`
- `assets/research.js`
- `data/research-packages.js`
- `categories/brainstorm/index.html`
- `categories/in-progress/index.html`
- `categories/success/index.html`
- `categories/fail/index.html`
- `package-template.html`
- `templates/module-library.html`

Required data globals:

- `window.RESEARCH_GLOBAL_CONTEXT`
- `window.RESEARCH_GLOBAL_PROTOCOL`
- `window.RESEARCH_PROJECT_PROFILE`
- `window.RESEARCH_CATEGORIES`
- `window.RESEARCH_TAG_ROLES`
- `window.RESEARCH_PACKAGES`

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

- `masthead`: title, lead paragraph, and toolbar with rules + README links.
- `nav`: in-page anchor nav over the remaining sections.
- `snapshot`: one `data-card="dashboard-role"` article that names this surface
  as overview + agent context, and points readers to package surfaces for
  claims and evidence.
- `lanes`: the four lane summary cells produced by `renderDashboardSummary()`.
- `protocol`: the global-protocol panels populated by `renderGlobalContext()`.
- `profile`: a `#project-profile-root` slot for project-specific specialization.
- `rules`: two cards with `data-card="rule-link-html"` and
  `data-card="rule-link-trust"` that link `rules/html-rules.html` and
  `rules/trustworthy-research-rules.html` and explain the difference.

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
