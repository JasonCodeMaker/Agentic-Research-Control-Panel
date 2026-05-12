(function () {
  var MODULES = [
    {
      id: "plan",
      title: "Plan",
      purpose: "Research objective, hypothesis, gates, budgets, baselines, no-change boundaries, and executable experiment list.",
      editHint: "Patch only workflow-owned plan cards: invariants, metric gates, experiment list, validation, and stop rules.",
    },
    {
      id: "tracker",
      title: "Tracker",
      purpose: "Single home for execution state: Resume Block, cross-stage to-do, Launch readiness card (T21/T16/T1), implementation review, resource allocation, per-run live cards (T22/T15), and latest live check.",
      editHint: "Update the Resume Block, append required table rows, fill the Launch readiness card before READY_TO_LAUNCH, and keep only the latest live check per open run.",
    },
    {
      id: "results",
      title: "Results",
      purpose: "Result gate entries, artifact validation, primary output, supported claims, unsupported claims, and next route.",
      editHint: "Add one factual Exp_Name date entry per completed experiment and verify artifacts before recording metrics.",
    },
    {
      id: "docs",
      title: "Docs",
      purpose: "Context dossier: method design, code anchors, metric/dataset/runtime contracts, audits, reviews, and references.",
      editHint: "Add source cards or source pages that reduce ambiguity before implementation, launch, review, or result analysis.",
    },
  ];

  function byId(id) {
    return document.getElementById(id);
  }

  function htmlEscape(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function normalizeCategory(category) {
    return String(category || "brainstorm").toLowerCase();
  }

  function categories() {
    return window.RESEARCH_CATEGORIES || [];
  }

  function packages() {
    return window.RESEARCH_PACKAGES || [];
  }

  function tagRoles() {
    return window.RESEARCH_TAG_ROLES || {};
  }

  function globalProtocol() {
    return window.RESEARCH_GLOBAL_PROTOCOL || {};
  }

  function globalContext() {
    return window.RESEARCH_GLOBAL_CONTEXT || {};
  }

  function projectProfile() {
    return window.RESEARCH_PROJECT_PROFILE || {};
  }

  function categoryById(categoryId) {
    return categories().find(function (category) {
      return category.id === categoryId;
    });
  }

  function packageById(packageId) {
    return packages().find(function (pkg) {
      return pkg.id === packageId;
    });
  }

  function tagRoleForCategory(category) {
    return tagRoles()[normalizeCategory(category)] || {
      role: "unknown",
      label: "Tag",
      meaning: "No tag-role mapping is defined for this category.",
      examples: [],
    };
  }

  function packageTag(pkg) {
    return pkg && pkg.tag ? pkg.tag : "untagged";
  }

  function packageTagMeaning(pkg) {
    return pkg && pkg.tagMeaning ? pkg.tagMeaning : "No tag meaning has been recorded.";
  }

  function moduleById(moduleId) {
    return MODULES.find(function (mod) {
      return mod.id === moduleId;
    });
  }

  function rootPrefix() {
    return window.RESEARCH_ROOT_PREFIX || "";
  }

  function queryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  function relativeDetailPath(pkg) {
    if (!pkg || !pkg.detailPath) return "#";
    if (window.RESEARCH_BASE_PREFIX) return window.RESEARCH_BASE_PREFIX + pkg.detailPath;
    return pkg.detailPath;
  }

  function countByCategory(categoryId) {
    return packages().filter(function (pkg) {
      return normalizeCategory(pkg.category) === categoryId;
    }).length;
  }

  function statusClass(category) {
    var normalized = normalizeCategory(category);
    if (normalized === "success") return "success";
    if (normalized === "fail") return "fail";
    if (normalized === "in-progress") return "progress";
    return "";
  }

  function tagBadgeHtml(pkg) {
    var role = tagRoleForCategory(pkg.category);
    return [
      '<span class="status package-tag ' + statusClass(pkg.category) + '"',
      ' data-tag-role="' + htmlEscape(role.role) + '"',
      ' data-tag="' + htmlEscape(packageTag(pkg)) + '"',
      ' title="' + htmlEscape(packageTagMeaning(pkg)) + '">',
      htmlEscape(packageTag(pkg)),
      "</span>",
    ].join("");
  }

  function tagSummaryHtml(pkg) {
    var role = tagRoleForCategory(pkg.category);
    return '<p class="card-text tag-summary"><strong>' + htmlEscape(role.label) + ":</strong> " + htmlEscape(packageTag(pkg)) + "</p>";
  }

  function renderDashboardSummary() {
    var target = byId("dashboard-summary");
    if (!target) return;
    target.innerHTML = categories().map(function (category) {
      return [
        '<a class="summary-cell summary-link" href="' + category.href + '" data-category="' + category.id + '">',
        '<div class="k">' + htmlEscape(category.title) + "</div>",
        '<div class="v">' + countByCategory(category.id) + "</div>",
        '<div class="hint">Open lane</div>',
        "</a>",
      ].join("");
    }).join("");
  }

  function renderGlobalContext() {
    var target = byId("global-context");
    var context = globalContext();
    if (!target || !context.objective) return;
    target.innerHTML = [
      protocolHeroHtml(context),
      protocolSectionHtml("Global Objectives", globalProtocol().objectiveCards, "protocol-objectives"),
      protocolSectionHtml("Agent Rules", globalProtocol().agentRules, "protocol-agent-rules"),
      protocolSectionHtml("Evidence Gates", globalProtocol().evidenceGates, "protocol-evidence-gates"),
      routeRulesHtml(),
      hardConstraintsHtml(),
      projectProfileHtml(),
      tagLegendHtml(),
    ].join("");
  }

  function protocolHeroHtml(context) {
    var protocol = globalProtocol();
    return [
      '<section class="protocol-panel protocol-hero" data-panel="global-protocol">',
      '<div class="k">Global purpose</div>',
      "<h2>Trustworthy Auto-Research Pipeline</h2>",
      "<p>" + htmlEscape(protocol.purpose || context.dashboardRole) + "</p>",
      '<div class="kv-grid protocol-kv">',
      '<div class="k">Global Objective</div><div>' + htmlEscape(context.objective) + "</div>",
      '<div class="k">Success Rule</div><div>' + htmlEscape(context.successRule) + "</div>",
      '<div class="k">Source Rule</div><div>' + htmlEscape(context.sourceOfTruth) + "</div>",
      "</div>",
      "</section>",
    ].join("");
  }

  function projectProfileHtml() {
    var profile = projectProfile();
    if (!profile.name) return "";
    var cards = profile.cards && profile.cards.length
      ? [
        '<div class="protocol-card-grid">',
        profile.cards.map(function (item) {
          return [
            '<article class="protocol-card">',
            "<h3>" + htmlEscape(item.title) + "</h3>",
            "<p>" + htmlEscape(item.body) + "</p>",
            "</article>",
          ].join("");
        }).join(""),
        "</div>",
      ].join("")
      : "";
    var constraints = profile.constraints && profile.constraints.length
      ? [
        '<ul class="constraint-list profile-constraints">',
        profile.constraints.map(function (constraint) {
          return "<li>" + htmlEscape(constraint) + "</li>";
        }).join(""),
        "</ul>",
      ].join("")
      : "";
    return [
      '<section class="protocol-panel project-profile" data-panel="project-profile">',
      '<div class="k">' + htmlEscape(profile.label || "Project profile") + "</div>",
      "<h2>" + htmlEscape(profile.name) + "</h2>",
      "<p>" + htmlEscape(profile.purpose || "") + "</p>",
      '<div class="kv-grid protocol-kv">',
      '<div class="k">Project Objective</div><div>' + htmlEscape(profile.objective || "Replace with the active project objective.") + "</div>",
      '<div class="k">Project Success Rule</div><div>' + htmlEscape(profile.successRule || "Replace with the project-specific success rule.") + "</div>",
      '<div class="k">Project Source Rule</div><div>' + htmlEscape(profile.sourceOfTruth || "Replace with the project-specific source-of-truth rule.") + "</div>",
      "</div>",
      cards,
      constraints,
      "</section>",
    ].join("");
  }

  function protocolSectionHtml(title, items, panelId) {
    if (!items || !items.length) return "";
    return [
      '<section class="protocol-panel" data-panel="' + htmlEscape(panelId) + '">',
      "<h2>" + htmlEscape(title) + "</h2>",
      '<div class="protocol-card-grid">',
      items.map(function (item) {
        return [
          '<article class="protocol-card">',
          "<h3>" + htmlEscape(item.title) + "</h3>",
          "<p>" + htmlEscape(item.body) + "</p>",
          "</article>",
        ].join("");
      }).join(""),
      "</div>",
      "</section>",
    ].join("");
  }

  function routeRulesHtml() {
    var routes = globalProtocol().routeRules || [];
    if (!routes.length) return "";
    return [
      '<section class="protocol-panel" data-panel="route-rules">',
      "<h2>Allowed Next Routes</h2>",
      '<div class="route-list">',
      routes.map(function (route) {
        return [
          '<article class="route-row" data-route="' + htmlEscape(route.route) + '">',
          "<code>" + htmlEscape(route.route) + "</code>",
          "<p>" + htmlEscape(route.meaning) + "</p>",
          "</article>",
        ].join("");
      }).join(""),
      "</div>",
      "</section>",
    ].join("");
  }

  function hardConstraintsHtml() {
    var constraints = globalProtocol().hardConstraints || [];
    if (!constraints.length) return "";
    return [
      '<section class="protocol-panel" data-panel="hard-constraints">',
      "<h2>Hard Constraints</h2>",
      '<ul class="constraint-list">',
      constraints.map(function (constraint) {
        return "<li>" + htmlEscape(constraint) + "</li>";
      }).join(""),
      "</ul>",
      "</section>",
    ].join("");
  }

  function tagLegendHtml() {
    var roles = tagRoles();
    var items = categories().map(function (category) {
      var role = roles[category.id];
      if (!role) return "";
      var examples = role.examples && role.examples.length
        ? '<div class="examples">Examples: ' + htmlEscape(role.examples.join(", ")) + "</div>"
        : "";
      return [
        '<article class="tag-role-card" data-category="' + htmlEscape(category.id) + '" data-tag-role="' + htmlEscape(role.role) + '">',
        '<div class="k">' + htmlEscape(category.title) + "</div>",
        '<div class="v">' + htmlEscape(role.label) + "</div>",
        '<p>' + htmlEscape(role.meaning) + "</p>",
        examples,
        "</article>",
      ].join("");
    }).join("");
    if (!items) return "";
    return [
      '<details class="details-panel small-details tag-legend">',
      "<summary>Category-scoped tag legend</summary>",
      '<div class="details-body tag-role-grid">',
      items,
      "</div>",
      "</details>",
    ].join("");
  }

  function unmeasuredHtml() {
    return '<span class="unmeasured" data-unmeasured="true">unmeasured</span>';
  }

  function fieldOrUnmeasured(value) {
    if (value == null || String(value).trim() === "") return unmeasuredHtml();
    return htmlEscape(value);
  }

  function chipHtml(kind, value) {
    var present = value != null && String(value).trim() !== "";
    var label = present ? value : "unmeasured";
    var attr = present ? htmlEscape(value) : "unmeasured";
    return '<span class="chip chip-' + kind + '" data-' + kind + '="' + attr + '">' + htmlEscape(label) + "</span>";
  }

  function lastUpdatedHtml(pkg) {
    var iso = pkg.lastUpdated;
    if (!iso) return unmeasuredHtml();
    return '<time data-field="last-updated" datetime="' + htmlEscape(iso) + '">' + htmlEscape(iso) + "</time>";
  }

  function packageCardHtml(pkg) {
    return [
      '<a class="package-card package-link-card" href="' + relativeDetailPath(pkg) + '" data-package-id="' + pkg.id + '" data-category="' + normalizeCategory(pkg.category) + '" data-route="' + htmlEscape(pkg.nextRoute || "unmeasured") + '" data-workflow-state="' + htmlEscape(pkg.workflowState || "unmeasured") + '">',
      '<div class="card-top">',
      tagBadgeHtml(pkg),
      chipHtml("workflow-state", pkg.workflowState),
      "</div>",
      '<div class="card-body">',
      '<h3 class="card-title">' + htmlEscape(pkg.name) + "</h3>",
      tagSummaryHtml(pkg),
      '<p class="card-text"><strong>Problem:</strong> ' + htmlEscape(pkg.problem) + "</p>",
      '<p class="card-text"><strong>Objective:</strong> ' + htmlEscape(pkg.objective) + "</p>",
      '<p class="card-text"><strong>Motivation:</strong> ' + htmlEscape(pkg.motivation) + "</p>",
      '<p class="card-text card-strip"><span><strong>Gate:</strong> ' + fieldOrUnmeasured(pkg.activeGate) + "</span> ",
      '<span><strong>Metric vs gate:</strong> ' + fieldOrUnmeasured(pkg.primaryMetricVsGate) + "</span></p>",
      '<p class="card-text card-strip"><span><strong>Next route:</strong> ' + chipHtml("route", pkg.nextRoute) + "</span> ",
      '<span><strong>Updated:</strong> ' + lastUpdatedHtml(pkg) + "</span></p>",
      "</div>",
      "</a>",
    ].join("");
  }

  function renderCategoryPage() {
    var root = byId("category-package-root");
    if (!root || !window.RESEARCH_CATEGORY_ID) return;

    var category = categoryById(window.RESEARCH_CATEGORY_ID);
    var items = packages().filter(function (pkg) {
      return normalizeCategory(pkg.category) === window.RESEARCH_CATEGORY_ID;
    });

    var title = byId("category-title");
    var summary = byId("category-summary");
    var count = byId("category-count");
    if (category && title) title.textContent = category.title;
    if (category && summary) summary.textContent = category.summary;
    if (count) count.textContent = String(items.length) + " packages";

    root.innerHTML = items.length
      ? items.map(packageCardHtml).join("")
      : '<div class="empty-state">No package is explicitly classified here yet.</div>';
  }

  function packageModuleHref(pkg, moduleId) {
    if (moduleId === "docs") return docsHref(pkg);
    return rootPrefix() + "module.html?package=" + encodeURIComponent(pkg.id) + "&module=" + encodeURIComponent(moduleId);
  }

  function modulePageHref(pkg, moduleId) {
    return packageModuleHref(pkg, moduleId);
  }

  function packageOverviewHref(pkg) {
    return rootPrefix() + "packages/" + pkg.id + "/";
  }

  function dashboardHref() {
    return rootPrefix() + "index.html";
  }

  function docsHref(pkg) {
    return rootPrefix() + "packages/" + pkg.id + "/docs/";
  }

  function agentContextHref(pkg) {
    return rootPrefix() + "packages/" + pkg.id + "/_agent/context.html";
  }

  function renderPackageDetail() {
    var root = byId("package-detail-root");
    if (!root || !window.RESEARCH_PACKAGE_ID) return;

    var pkg = packageById(window.RESEARCH_PACKAGE_ID);
    if (!pkg) {
      root.innerHTML = '<div class="empty-state">Package metadata was not found.</div>';
      return;
    }

    document.title = pkg.name + " - Research Package";
    root.innerHTML = [
      '<div class="shell">',
      '<header class="masthead">',
      '<div class="eyebrow">Research package overview</div>',
      "<h1>" + htmlEscape(pkg.name) + "</h1>",
      '<p class="lead">' + htmlEscape(pkg.problem) + "</p>",
      '<div class="toolbar">',
      tagBadgeHtml(pkg),
      '<span class="tag">' + htmlEscape(pkg.category) + "</span>",
      '<a class="pill" href="' + dashboardHref() + '">Dashboard</a>',
      '<a class="pill" href="' + rootPrefix() + 'categories/' + pkg.category + '/">Category</a>',
      "</div>",
      "</header>",
      overviewOnly(pkg),
      moduleGrid(pkg),
      '<footer class="footer-note">Package home is Overview first. Open Plan, Tracker, Results, or Docs for details. Continuity and verification context is summarized in Overview and mirrored at <code>_agent/context.html</code>.</footer>',
      "</div>",
    ].join("");
  }

  function overviewOnly(pkg) {
    return [
      '<section class="module" id="overview" data-module="overview">',
      '<div class="module-header"><span class="idx">01</span><h2>Overview</h2></div>',
      '<div class="module-grid">',
      '<article class="module-card" id="overview-summary">',
      "<h3>Research Context</h3>",
      '<div class="kv-grid">',
      '<div class="k">Problem</div><div data-field="problem">' + htmlEscape(pkg.problem) + "</div>",
      '<div class="k">Objective</div><div data-field="objective">' + htmlEscape(pkg.objective) + "</div>",
      '<div class="k">Motivation</div><div data-field="motivation">' + htmlEscape(pkg.motivation) + "</div>",
      '<div class="k">' + htmlEscape(tagRoleForCategory(pkg.category).label) + '</div><div data-tag-role="' + htmlEscape(tagRoleForCategory(pkg.category).role) + '" data-tag="' + htmlEscape(packageTag(pkg)) + '" title="' + htmlEscape(packageTagMeaning(pkg)) + '">' + htmlEscape(packageTag(pkg)) + "</div>",
      '<div class="k">Category</div><div data-field="category">' + htmlEscape(pkg.category) + "</div>",
      "</div>",
      "</article>",
      '<article class="module-card" id="overview-paths">',
      "<h3>Path Anchors</h3>",
      '<div class="artifact-list">',
      '<div class="artifact-row"><div class="kind">source package</div><code data-artifact="source-package">' + htmlEscape(pkg.sourcePath) + "</code></div>",
      '<div class="artifact-row"><div class="kind">artifact root</div><code data-artifact="artifact-root">' + htmlEscape(pkg.runtime) + "</code></div>",
      '<div class="artifact-row"><div class="kind">html package</div><code data-artifact="html-package">research_html/' + htmlEscape(pkg.detailPath) + "</code></div>",
      '<div class="artifact-row"><div class="kind">docs folder</div><code data-artifact="html-docs">' + htmlEscape("research_html/" + pkg.detailPath + "docs/") + "</code></div>",
      '<div class="artifact-row"><div class="kind">continuity file</div><code data-artifact="continuity-file">' + htmlEscape("research_html/" + pkg.detailPath + "_agent/context.html") + "</code></div>",
      "</div>",
      "</article>",
      '<article class="module-card" id="overview-continuity" data-card="continuity-verification">',
      "<h3>Continuity &amp; Verification</h3>",
      '<div class="kv-grid">',
      '<div class="k">Resume from</div><div data-field="resume-path">Open Tracker for current state, then open only the module needed for the next action.</div>',
      '<div class="k">Verify before results</div><div data-field="verification-rule">Use the source package and artifact root above as the source of truth before changing Results or package status.</div>',
      '<div class="k">Source context</div><div><a href="' + docsHref(pkg) + '">Open Docs</a></div>',
      '<div class="k">Raw continuity file</div><div><a href="' + agentContextHref(pkg) + '">Open _agent/context.html</a></div>',
      "</div>",
      "</article>",
      '<article class="module-card" id="overview-workflow" data-card="workflow-state">',
      "<h3>Workflow State &amp; Gate</h3>",
      '<div class="kv-grid">',
      '<div class="k">State</div><div data-workflow-state>Read Tracker Resume Block, then verify live/runtime state.</div>',
      '<div class="k">Active Gate</div><div data-gate>Use the active plan metrics, budgets, baselines, and stop gates as authority.</div>',
      '<div class="k">Next Route</div><div data-route>run_next_experiment_from_step4 | fix_implementation | revise_plan | archive_or_stop | ask_user</div>',
      '<div class="k">Decision Record</div><div data-field="decision-record">Persist only concise Decision / Evidence Used in the owning module.</div>',
      "</div>",
      "</article>",
      "</div>",
      "</section>",
    ].join("");
  }

  function moduleGrid(pkg) {
    return [
      '<section class="module" id="modules" data-module="module-index">',
      '<div class="module-header"><span class="idx">02</span><h2>User Modules</h2></div>',
      '<div class="subcard-grid">',
      MODULES.map(function (mod) {
        return [
          '<a class="module-link-card" href="' + packageModuleHref(pkg, mod.id) + '" data-submodule="' + mod.id + '">',
          '<div class="card-top"><span class="tag">' + htmlEscape(mod.id) + "</span></div>",
          '<div class="card-body">',
          '<h3 class="card-title">' + htmlEscape(mod.title) + "</h3>",
          '<p class="card-text">' + htmlEscape(mod.purpose) + "</p>",
          '<p class="card-text"><strong>Edit unit:</strong> ' + htmlEscape(mod.editHint) + "</p>",
          "</div>",
          "</a>",
        ].join("");
      }).join(""),
      "</div>",
      '<div class="notice" style="margin-top:18px;">Evidence and resume are not separate modules. They are expressed as Continuity &amp; Verification in Overview, with exact source paths mirrored in <code>_agent/context.html</code>.</div>',
      "</section>",
    ].join("");
  }

  function renderModulePage() {
    var root = byId("package-module-root");
    if (!root) return;

    var packageId = window.RESEARCH_PACKAGE_ID || queryParam("package");
    var moduleId = window.RESEARCH_PACKAGE_MODULE || queryParam("module");
    var pkg = packageById(packageId);
    var mod = moduleById(moduleId);
    if (!pkg || !mod) {
      root.innerHTML = '<div class="shell"><div class="empty-state">Package or module metadata was not found.</div></div>';
      return;
    }

    document.title = pkg.name + " - " + mod.title;
    root.innerHTML = [
      '<div class="shell page-grid">',
      '<nav class="side-nav" aria-label="Package modules">',
      '<div class="label">Package modules</div>',
      MODULES.map(function (item) {
        return '<a href="' + modulePageHref(pkg, item.id) + '">' + htmlEscape(item.title) + "</a>";
      }).join(""),
      "</nav>",
      "<main>",
      '<header class="masthead">',
      '<div class="eyebrow">Package module</div>',
      "<h1>" + htmlEscape(mod.title) + "</h1>",
      '<p class="lead">' + htmlEscape(pkg.name) + ": " + htmlEscape(mod.purpose) + "</p>",
      '<div class="toolbar">',
      '<a class="pill" href="' + packageOverviewHref(pkg) + '">Package Overview</a>',
      '<a class="pill" href="' + dashboardHref() + '">Dashboard</a>',
      '<span class="tag">' + htmlEscape(pkg.category) + "</span>",
      "</div>",
      "</header>",
      moduleContent(pkg, mod),
      '<footer class="footer-note">This module is intentionally isolated. Keep edits local to this module unless the package overview or shared template must change.</footer>',
      "</main>",
      "</div>",
    ].join("");

    setupCopyButtons();
  }

  function moduleContent(pkg, mod) {
    if (mod.id === "plan") return planContent(pkg);
    if (mod.id === "tracker") return trackerContent(pkg);
    if (mod.id === "results") return resultsContent(pkg);
    if (mod.id === "docs") return docsContent(pkg);
    return '<div class="empty-state">Unknown module.</div>';
  }

  function planContent() {
    return [
      '<section class="module" data-module="plan">',
      '<div class="module-header"><span class="idx">01</span><h2>Plan Cards</h2></div>',
      '<div class="subcard-grid">',
      '<article class="module-card" id="plan-global" data-card="global-part"><h3>Global Part</h3><div class="kv-grid"><div class="k">Objective</div><div data-field="global-objective">Direction-level research objective.</div><div class="k">Hypothesis</div><div data-field="hypothesis">State the learning, retrieval, data, system, or evaluation hypothesis.</div><div class="k">No-Change Boundary</div><div data-field="no-change-boundary">List architecture, dataset, metric, runtime, or claim boundaries that must not drift.</div></div></article>',
      '<article class="module-card" id="plan-gates" data-card="metric-gates"><h3>Metric Gates &amp; Budgets</h3><div class="kv-grid"><div class="k">Primary Metric</div><div data-field="primary-metric">Objective metric tied to the research claim.</div><div class="k">Baseline</div><div data-field="baseline">Reference artifact, config, protocol, or prior result.</div><div class="k">Budget Gate</div><div data-gate>Compute, data, latency, quality, seed, or resource budget.</div><div class="k">Early Stop</div><div data-field="early-stop">Only active-plan thresholds can trigger early stop.</div></div></article>',
      '<article class="module-card" id="plan-local" data-card="local-part"><h3>Local Part</h3><p data-field="local-objective">Latest executable plan only. Replace this card when the approved active plan changes.</p><div class="notice">Do not preserve obsolete plan history here; record completed evidence in Results and execution state in Tracker.</div></article>',
      '<article class="module-card" id="plan-experiments" data-card="experiments-list"><h3>Experiments List</h3><ol data-field="experiments-list"><li>Each item should include purpose, config, dependency, command owner, expected artifacts, and success/failure gate.</li></ol><p class="card-text">Per-experiment <em>status</em> is not part of this spec list. It is owned by the tracker resource-allocation row and painted onto <code>index.html#plan-status</code> by <code>renderPlanStatus()</code> from <code>experiments[]</code> in <code>data/research-packages.js</code>.</p></article>',
      '<article class="module-card" id="plan-validation" data-card="validation-plan"><h3>Validation Plan</h3><p data-field="validation">List the cheapest checks before launch: syntax, dry-run manifest, forbidden-knob rejection, path discovery, artifact contract, and metric recomputation.</p></article>',
      '<article class="module-card" id="plan-stop-rule" data-card="stop-rule"><h3>Stop Rule</h3><p data-field="stop-rule">Define when this package should stop, archive, ask the user, or route back to implementation.</p></article>',
      "</div>",
      "</section>",
    ].join("");
  }

  function trackerContent() {
    return [
      '<section class="module" data-module="tracker">',
      '<div class="module-header"><span class="idx">01</span><h2>Tracker Cards</h2></div>',
      '<div class="subcard-grid">',
      '<article class="module-card" data-card="resume-block"><h3>Resume Block</h3><div class="kv-grid"><div class="k">Current State</div><div data-workflow-state>CONTEXT_LOADED | IMPLEMENTING | READY_TO_LAUNCH | EXPERIMENT_RUNNING | RESULT_ANALYSIS | BLOCKED | STOPPED</div><div class="k">Active Plan</div><div data-field="active-plan">Plan section, spec section, or experiment name.</div><div class="k">Last Action</div><div data-field="last-action">Timestamp plus command, edit, or observation.</div><div class="k">Next Action</div><div data-next-action>Single concrete next step.</div><div class="k">Artifact Root</div><code data-artifact="artifact-root">artifacts/research/...</code><div class="k">Open Runs</div><div data-field="open-runs">session/job ids or none.</div><div class="k">Blocking Issue</div><div data-field="blocking-issue">none or concrete blocker.</div></div></article>',
      '<article class="module-card" data-card="implementation-review"><h3>Implementation Review</h3><table class="data-table" data-table="implementation-review"><thead><tr><th>Change ID</th><th>Purpose</th><th>Unit</th><th>Owned Files</th><th>Reviewer Verdict</th><th>Finding Class</th><th>Required Fix</th><th>Main Decision</th><th>Validation</th></tr></thead><tbody><tr><td>change_id</td><td>purpose</td><td>unit</td><td>files</td><td>pass|needs_fix|blocked</td><td>blocking|non_blocking|question|invalid</td><td>fix</td><td data-decision>Decision / Evidence Used</td><td>checks</td></tr></tbody></table></article>',
      '<article class="module-card" data-card="resource-allocation"><h3>Resource Allocation</h3><table class="data-table" data-table="resource-allocation"><thead><tr><th>Exp ID</th><th>Purpose</th><th>Dependency</th><th>Target</th><th>Capacity</th><th>Command/CWD/Env</th><th>Session/Job</th><th>Artifact Root</th><th>Log Path</th><th>Status</th></tr></thead><tbody><tr><td>exp_id</td><td>purpose</td><td>dependency</td><td>resource/job</td><td>live snapshot</td><td><code class="command">command</code></td><td>session</td><td>artifact root</td><td>log</td><td>queued|running|completed|failed|blocked</td></tr></tbody></table></article>',
      '<article class="module-card" data-card="latest-live-check"><h3>Latest Live Check</h3><table class="data-table" data-table="live-check"><thead><tr><th>Time</th><th>Exp ID</th><th>Run State</th><th>Progress</th><th>Latest Metrics</th><th>Resource Use</th><th>Artifact Status</th><th>ETA</th><th>Live Action</th><th>Next Check</th></tr></thead><tbody><tr><td>time</td><td>exp_id</td><td>running|stale|completed</td><td>phase/epoch</td><td>objective metric only</td><td>resource/job</td><td>ok|missing</td><td>eta</td><td>continue|repair|ask_user|blocked</td><td>time</td></tr></tbody></table><p>Keep only the latest live check here. Detailed logs belong in artifacts.</p></article>',
      '<article class="module-card" data-card="launch-command"><h3>Launch Command Template</h3><pre class="code-box"><code id="tracker-launch-command" class="command">run-experiment-command --config configs/experiment.yaml --output artifacts/research/...</code></pre><button class="copy-button" type="button" data-copy-target="#tracker-launch-command">Copy Command</button></article>',
      '<article class="module-card" data-card="decision-log"><h3>Concise Decision</h3><p data-decision>Decision: route or judgment. Evidence Used: files, artifacts, runtime facts, or subagent reports.</p></article>',
      "</div>",
      "</section>",
    ].join("");
  }

  function resultsContent() {
    return [
      '<section class="module" data-module="results">',
      '<div class="module-header"><span class="idx">01</span><h2>Result Cards</h2></div>',
      '<div class="subcard-grid">',
      '<article class="module-card exp-card" data-exp-id="template"><h3>Exp_Name (date)</h3><div class="metric-strip"><div class="metric-card"><div class="k">Validity</div><div class="v" data-field="validity">--</div></div><div class="metric-card"><div class="k">Primary</div><div class="v" data-metric="primary">--</div></div><div class="metric-card"><div class="k">Budget</div><div class="v" data-metric="budget">--</div></div><div class="metric-card"><div class="k">Verdict</div><div class="v" data-decision>--</div></div></div></article>',
      '<article class="module-card" data-card="result-gate"><h3>Result Gate</h3><table class="data-table" data-table="result-gate"><thead><tr><th>Exp ID</th><th>Validity</th><th>Baseline</th><th>PLAN Gate</th><th>Observed Metric</th><th>Budget/Resource Use</th><th>Seed Status</th><th>Artifact Completeness</th><th>Verdict</th><th>Reason</th></tr></thead><tbody><tr><td>exp_id</td><td>valid|invalid</td><td>baseline</td><td>gate</td><td>metric</td><td>budget</td><td>seed</td><td>artifacts</td><td data-decision>pass|fail|diagnostic</td><td>reason</td></tr></tbody></table></article>',
      '<article class="module-card" data-card="artifact-verification"><h3>Artifact Verification</h3><div class="artifact-list"><div class="artifact-row"><div class="kind">primary artifact</div><code data-artifact="primary-artifact">artifacts/research/.../primary_output</code></div><div class="artifact-row"><div class="kind">log</div><code data-artifact="log">artifacts/research/.../logs/run.log</code></div><div class="artifact-row"><div class="kind">summary</div><code data-artifact="summary">artifacts/research/.../summaries/result.json</code></div></div><p>Before recording numbers, verify artifacts exist, match the experiment id/config, and were modified after launch.</p></article>',
      '<article class="module-card" data-card="analysis"><h3>Supported Claims</h3><p data-field="analysis">Concise interpretation tied to PLAN objective, gates, baseline, budget, seed status, and artifact completeness.</p></article>',
      '<article class="module-card" data-card="unsupported-claims"><h3>Unsupported Claims</h3><p data-field="unsupported-claims">List claims this result does not support, including metric, seed, budget, route, or rerank limitations.</p></article>',
      '<article class="module-card" data-card="next-action"><h3>Step 7 Next Action</h3><div class="kv-grid"><div class="k">Route</div><div data-route>run_next_experiment_from_step4 | fix_implementation | revise_plan | archive_or_stop | ask_user</div><div class="k">Reason</div><div data-field="next-action-reason">Apply PLAN gates to verified evidence.</div><div class="k">Decision</div><div data-decision>Decision / Evidence Used</div></div></article>',
      "</div>",
      "</section>",
    ].join("");
  }

  function docsContent(pkg) {
    return [
      '<section class="module" data-module="docs">',
      '<div class="module-header"><span class="idx">01</span><h2>Docs</h2></div>',
      '<div class="notice">Docs are the Context Dossier for the user and Codex. They should resolve ambiguity before implementation, launch, review, monitoring, or result analysis.</div>',
      '<div class="subcard-grid">',
      '<article class="module-card" data-doc-card="source-index"><h3>Source Index</h3><div class="artifact-list"><div class="artifact-row"><div class="kind">old source root</div><code data-artifact="old-docs-root">' + htmlEscape(pkg.sourcePath) + 'docs/</code></div><div class="artifact-row"><div class="kind">html docs folder</div><code data-artifact="html-docs">research_html/' + htmlEscape(pkg.detailPath) + 'docs/</code></div><div class="artifact-row"><div class="kind">continuity file</div><code data-artifact="continuity-file">research_html/' + htmlEscape(pkg.detailPath) + '_agent/context.html</code></div></div></article>',
      '<article class="module-card" data-doc-card="context-dossier"><h3>Context Dossier</h3><ul><li>Invocation and active objective.</li><li>Plan/spec clauses, gates, budgets, commands, and no-change boundaries.</li><li>Prior Tracker and Results facts.</li><li>Verified code anchors, artifact roots, and validation checks.</li><li>Known ambiguities and assumptions that must not be invented.</li></ul></article>',
      '<article class="module-card" data-doc-card="method-design"><h3>Method Design</h3><p data-field="source-summary">Explain the method, model, training, data, or evaluation change; compatibility constraints; code anchors; and why it sharpens the project objective.</p></article>',
      '<article class="module-card" data-doc-card="contracts"><h3>Metric, Dataset, Runtime Contracts</h3><p data-field="source-summary">Define primary metrics, diagnostic metrics, baselines, budgets, dataset splits, feature roots, launch environment, and artifact paths.</p></article>',
      '<article class="module-card" data-doc-card="reviews"><h3>Reviews And Audits</h3><p data-field="source-summary">Store implementation reviews, result analyses, novelty/claim concerns, failed assumptions, and resolved reviewer attacks.</p></article>',
      "</div>",
      "</section>",
    ].join("");
  }

  var STAGE_PAGES = [
    { slug: "overview", label: "Overview", href: "index.html" },
    { slug: "plan", label: "Plan", href: "plan.html" },
    { slug: "implementation", label: "Implementation", href: "implementation.html" },
    { slug: "results", label: "Results", href: "results.html" },
    { slug: "next-action", label: "Next action", href: "next-action.html" },
    { slug: "tracker", label: "Tracker", href: "tracker.html" },
    { slug: "docs", label: "Docs", href: "docs/" },
    { slug: "brainstorm", label: "Brainstorm", href: "brainstorm.html" },
  ];

  var ALWAYS_PRESENT_PAGES = ["overview", "tracker", "docs"];

  function currentPackage() {
    var id = window.RESEARCH_PACKAGE_ID;
    return id ? packageById(id) : null;
  }

  function statusStripCellHtml(label, fieldName, value, opts) {
    opts = opts || {};
    var dataset = opts.dataset ? ' data-' + opts.dataset + '="' + htmlEscape(value || "unmeasured") + '"' : "";
    var hint = opts.hint ? '<div class="hint" data-field="' + opts.hintField + '">' + fieldOrUnmeasured(opts.hint) + "</div>" : "";
    return [
      '<div class="status-cell">',
      '<div class="k">' + htmlEscape(label) + "</div>",
      '<div class="v" data-field="' + fieldName + '"' + dataset + ">" + fieldOrUnmeasured(value) + "</div>",
      hint,
      "</div>",
    ].join("");
  }

  function renderStatusStrip() {
    var hosts = document.querySelectorAll("[data-status-strip]");
    if (!hosts.length) return;
    var pkg = currentPackage();
    if (!pkg) return;
    var html = [
      statusStripCellHtml("State", "workflow-state", pkg.workflowState, { dataset: "workflow-state" }),
      statusStripCellHtml("Active gate", "active-gate", pkg.activeGate),
      statusStripCellHtml("Metric vs gate", "primary-metric-vs-gate", pkg.primaryMetricVsGate),
      statusStripCellHtml("Last decision", "last-decision", pkg.lastDecision, { hint: pkg.lastDecisionEvidencePath, hintField: "last-decision-evidence" }),
      statusStripCellHtml("Next route", "next-route", pkg.nextRoute, { dataset: "route" }),
      statusStripCellHtml("Blocker", "current-blocker", pkg.currentBlocker),
    ].join("");
    hosts.forEach(function (host) { host.innerHTML = html; });
    var pageTime = document.querySelector('time[data-field="last-updated"]');
    var pageISO = pageTime && pageTime.getAttribute("datetime");
    if (pkg.lastUpdated && pageISO && pageISO < pkg.lastUpdated) {
      document.documentElement.setAttribute("data-stale", "true");
    }
  }

  function packagePrefix() {
    var root = window.RESEARCH_ROOT_PREFIX || "";
    return root.indexOf("../../") === 0 ? root.slice(6) : "";
  }

  function renderPackageNav() {
    var hosts = document.querySelectorAll("[data-package-nav]");
    if (!hosts.length) return;
    var pkg = currentPackage();
    if (!pkg) return;
    var present = pkg.pages || [];
    var category = normalizeCategory(pkg.category);
    var prefix = packagePrefix();
    var html = STAGE_PAGES.filter(function (p) {
      if (p.slug === "brainstorm") return category === "brainstorm";
      return true;
    }).map(function (p) {
      var isPresent = present.indexOf(p.slug) >= 0 || ALWAYS_PRESENT_PAGES.indexOf(p.slug) >= 0;
      var href = prefix + p.href;
      if (isPresent) {
        return '<a class="package-nav-link" href="' + htmlEscape(href) + '" data-page-link="' + p.slug + '">' + htmlEscape(p.label) + "</a>";
      }
      return '<span class="package-nav-link disabled" aria-disabled="true" data-page-link="' + p.slug + '" title="page not yet created">' + htmlEscape(p.label) + "</span>";
    }).join("");
    hosts.forEach(function (host) { host.innerHTML = html; });
  }

  function renderResumeBlock() {
    var card = document.querySelector('[data-card="resume-block"]');
    if (!card) return;
    var pkg = currentPackage();
    if (!pkg) return;
    var pairs = [
      ["workflow-state", pkg.workflowState],
      ["last-action", pkg.lastAction],
      ["open-runs", pkg.openRuns],
      ["blocking-issue", pkg.currentBlocker],
    ];
    pairs.forEach(function (pair) {
      var el = card.querySelector('[data-field="' + pair[0] + '"]');
      if (!el) return;
      if (pair[1] != null && String(pair[1]).trim() !== "") {
        el.textContent = String(pair[1]);
        if (pair[0] === "workflow-state") el.setAttribute("data-workflow-state", String(pair[1]));
      }
    });
  }

  function renderValidityCounts() {
    var summary = document.querySelector('[data-card="validity-summary"]');
    if (!summary) return;
    var rows = document.querySelectorAll('[data-table="result-gate"] tbody tr');
    if (!rows.length) return;
    var counts = { valid: 0, diagnostic_only: 0, failed: 0, missing: 0 };
    rows.forEach(function (tr) {
      var cell = tr.querySelector("[data-validity]");
      if (!cell) return;
      var v = cell.getAttribute("data-validity");
      if (counts[v] != null) counts[v] += 1;
    });
    Object.keys(counts).forEach(function (k) {
      var chip = summary.querySelector('.chip[data-validity="' + k + '"]');
      if (chip) chip.textContent = k + " " + counts[k];
    });
  }

  function renderPlanStatus() {
    var host = document.querySelector('[data-card="plan-status"] [data-field="plan-status-list"]');
    if (!host) return;
    var pkg = currentPackage();
    if (!pkg) return;
    var items = Array.isArray(pkg.experiments) ? pkg.experiments : [];
    if (!items.length) {
      host.innerHTML = '<div class="empty-state">No experiments declared in inventory. See <a href="plan.html#experiments">plan / experiments</a>.</div>';
      return;
    }
    host.innerHTML = items.map(function (e) {
      var id = e && e.id ? String(e.id) : "unmeasured";
      var label = e && e.label ? String(e.label) : "";
      var status = e && e.status ? String(e.status) : "pending";
      var run = e && e.runLink ? String(e.runLink) : "tracker.html#resource-allocation";
      return [
        '<div class="plan-status-row" data-exp-status-binding="' + htmlEscape(id) + '">',
        '<span class="exp-id"><a href="plan.html#experiments">' + htmlEscape(id) + "</a></span>",
        label ? '<span class="exp-label">' + htmlEscape(label) + "</span>" : "",
        '<span class="chip" data-status="' + htmlEscape(status) + '">' + htmlEscape(status) + "</span>",
        '<a class="exp-run-link" href="' + htmlEscape(run) + '">run</a>',
        "</div>",
      ].join("");
    }).join("");
  }

  function renderHypothesisCheck() {
    var nodes = document.querySelectorAll("[data-hypothesis-restated]");
    if (!nodes.length) return;
    var pkg = currentPackage();
    if (!pkg || !pkg.hypothesis) return;
    var canonical = String(pkg.hypothesis).trim().toLowerCase().replace(/\s+/g, " ");
    nodes.forEach(function (node) {
      var page = String(node.textContent || "").trim().toLowerCase().replace(/\s+/g, " ");
      if (canonical && page && canonical !== page) {
        node.setAttribute("data-hypothesis-mismatch", "true");
      } else {
        node.removeAttribute("data-hypothesis-mismatch");
      }
    });
  }

  function distinctSorted(values) {
    var out = [];
    values.forEach(function (v) { if (out.indexOf(v) === -1) out.push(v); });
    return out.sort();
  }

  function buildPackageFilterForm(form, lanes, routes) {
    var laneCheckboxes = lanes.map(function (id) {
      return '<label><input type="checkbox" name="lane" value="' + htmlEscape(id) + '" checked> ' + htmlEscape(id) + "</label>";
    }).join(" ");
    var routeOptions = ['<option value="all">All routes</option>'].concat(routes.map(function (r) {
      return '<option value="' + htmlEscape(r) + '">' + htmlEscape(r) + "</option>";
    })).join("");
    form.innerHTML = [
      '<fieldset class="filter-group"><legend>Lane</legend>' + laneCheckboxes + "</fieldset>",
      '<fieldset class="filter-group"><legend>Next route</legend><select name="route">' + routeOptions + "</select></fieldset>",
      '<fieldset class="filter-group"><legend>Sort</legend><select name="sort"><option value="recency">Most recent</option><option value="category">By lane</option></select></fieldset>',
    ].join("");
  }

  function paintDashboardPackages(form, root) {
    var lanes = form ? Array.prototype.map.call(form.querySelectorAll('input[name="lane"]:checked'), function (i) { return i.value; }) : null;
    var route = form && form.elements.route ? form.elements.route.value : "all";
    var sort = form && form.elements.sort ? form.elements.sort.value : "recency";
    var items = packages().slice();
    if (lanes && lanes.length) items = items.filter(function (p) { return lanes.indexOf(normalizeCategory(p.category)) >= 0; });
    if (route !== "all") items = items.filter(function (p) { return (p.nextRoute || "unmeasured") === route; });
    if (sort === "recency") {
      items.sort(function (a, b) { return String(b.lastUpdated || "").localeCompare(String(a.lastUpdated || "")); });
    } else {
      items.sort(function (a, b) { return String(a.category).localeCompare(String(b.category)); });
    }
    root.innerHTML = items.length
      ? items.map(packageCardHtml).join("")
      : '<div class="empty-state">No packages match the current filters.</div>';
  }

  function renderDashboardPackages() {
    var root = byId("dashboard-package-root");
    if (!root) return;
    var form = document.querySelector('[data-card="package-filters"]');
    var lanes = distinctSorted(packages().map(function (p) { return normalizeCategory(p.category); }));
    var routes = distinctSorted(packages().map(function (p) { return p.nextRoute || "unmeasured"; }));
    if (form && form.dataset.bound !== "1") {
      form.dataset.bound = "1";
      buildPackageFilterForm(form, lanes, routes);
      form.addEventListener("change", function () { paintDashboardPackages(form, root); });
    }
    paintDashboardPackages(form, root);
  }

  function setupCopyButtons() {
    document.querySelectorAll("[data-copy-target]").forEach(function (button) {
      if (button.dataset.copyBound === "1") return;
      button.dataset.copyBound = "1";
      button.addEventListener("click", function () {
        var target = document.querySelector(button.getAttribute("data-copy-target"));
        if (!target) return;
        var text = target.innerText || target.textContent || "";
        navigator.clipboard.writeText(text).then(function () {
          var old = button.textContent;
          button.textContent = "Copied";
          window.setTimeout(function () {
            button.textContent = old;
          }, 900);
        });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    renderDashboardSummary();
    renderGlobalContext();
    renderCategoryPage();
    renderPackageDetail();
    renderModulePage();
    renderStatusStrip();
    renderPackageNav();
    renderResumeBlock();
    renderPlanStatus();
    renderValidityCounts();
    renderHypothesisCheck();
    renderDashboardPackages();
    setupCopyButtons();
  });
})();
