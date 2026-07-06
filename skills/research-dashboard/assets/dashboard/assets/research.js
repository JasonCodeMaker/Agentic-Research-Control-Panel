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
    // Package category is one of the lane facets (in-progress / success / fail).
    // Brainstorm is no longer a package category (it is the ideas-only lane), so
    // there is no brainstorm fallback here; a category-less package matches no lane.
    return String(category || "").toLowerCase();
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

  function rulesRegistry() {
    return window.RESEARCH_RULES || [];
  }

  function projectProfile() {
    return window.RESEARCH_PROJECT_PROFILE || {};
  }

  function scopeProjection() {
    return window.RESEARCH_SCOPE_PROJECTION || {};
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
    // Brainstorm is a lane (window.BRAINSTORMS), not a package category; count the ideas.
    if (categoryId === "brainstorm") return (window.BRAINSTORMS || []).length;
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
    // The lane summary section uses id="lanes" (for the dashboard-nav anchor)
    // and class="dashboard-summary" (for styling). Query by class so the
    // anchor stays correct.
    var target = document.querySelector(".dashboard-summary") || byId("dashboard-summary");
    if (!target) return;
    target.innerHTML = categories().map(function (category) {
      return [
        '<a class="summary-cell summary-link" href="' + htmlEscape(category.href) + '" data-category="' + htmlEscape(category.id) + '">',
        '<div class="k">' + htmlEscape(category.title) + "</div>",
        '<div class="v">' + countByCategory(category.id) + "</div>",
        '<div class="hint">Open lane</div>',
        "</a>",
      ].join("");
    }).join("");
  }

  function renderGlobalContext() {
    var target = byId("global-context");
    if (!target) return;
    target.innerHTML = [
      objectivePanelHtml(),
      routesPanelHtml(),
      protocolLinksHtml(),
      tagLegendHtml(),
    ].join("");
  }

  function renderProjectProfile() {
    var target = byId("project-profile-root");
    if (!target) return;
    target.innerHTML = projectProfileHtml();
  }

  function ruleRowHtml(rule) {
    return [
      '<article class="rule-row" data-rule-id="' + htmlEscape(rule.id) + '" data-rule-status="' + htmlEscape(rule.status) + '">',
      "<code>" + htmlEscape(rule.id) + "</code>",
      "<div><strong>" + htmlEscape(rule.title) + "</strong>",
      rule.text ? "<p>" + htmlEscape(rule.text) + "</p>" : "",
      "</div></article>",
    ].join("");
  }

  function renderRulesRegistry() {
    // The one surface answering "which rules bind me right now" — a pure render
    // of data/rules.js (universal mirror + project rows + package rows).
    var target = byId("rules-registry-root");
    if (!target) return;
    var rules = rulesRegistry();
    var groups = [
      { title: "Universal (write-locked)", open: false, match: function (r) { return r.level === "universal"; } },
      { title: "Project rules", open: true, match: function (r) { return r.level === "project" && r.status === "ACTIVE"; } },
      { title: "Package rules", open: true, match: function (r) { return r.level === "package" && r.status === "ACTIVE"; } },
    ];
    target.innerHTML = groups.map(function (group) {
      var rows = rules.filter(group.match);
      return [
        '<details class="details-panel rules-group"' + (group.open ? " open" : "") + ">",
        "<summary>" + htmlEscape(group.title) + " (" + rows.length + ")</summary>",
        rows.length ? rows.map(ruleRowHtml).join("") : '<p class="card-text">None.</p>',
        "</details>",
      ].join("");
    }).join("");
  }

  function renderScopeProjection() {
    var target = byId("scope-projection-root");
    if (!target) return;
    var projection = scopeProjection();
    var ids = Object.keys(projection);
    if (!ids.length) {
      target.innerHTML = '<div class="empty-state">No Scope SSOT projection has been rendered yet.</div>';
      return;
    }
    var nodes = ids.map(function (id) { return projection[id]; }).filter(Boolean);
    var projects = nodes.filter(function (node) { return node.level === "project"; });
    var directions = nodes.filter(function (node) { return node.level === "direction" && node.status === "ACTIVE"; });
    var tasks = nodes.filter(function (node) { return node.level === "task" && node.status === "ACTIVE"; });
    var projectHtml = projects.length
      ? projects.map(scopeProjectHtml).join("")
      : '<article class="scope-node scope-node-project"><h3>Project</h3><p class="card-text">No Project node found.</p></article>';
    var directionHtml = directions.length
      ? directions.map(function (direction) {
        var children = tasks.filter(function (task) {
          return (task.parents || []).indexOf(direction.id) >= 0;
        });
        return scopeDirectionHtml(direction, children);
      }).join("")
      : '<article class="scope-node"><h3>Directions</h3><p class="card-text">No active Direction nodes found.</p></article>';
    target.innerHTML = [
      '<div class="scope-projection-layout">',
      projectHtml,
      '<div class="scope-direction-list">',
      directionHtml,
      "</div>",
      "</div>",
    ].join("");
  }

  function scopeSpec(node) {
    return (node && node.spec) || {};
  }

  function scopeList(value) {
    if (Array.isArray(value)) {
      return '<ul class="scope-list">' + value.map(function (item) {
        return "<li>" + htmlEscape(item) + "</li>";
      }).join("") + "</ul>";
    }
    return '<p class="scope-value">' + htmlEscape(value || "unmeasured") + "</p>";
  }

  function scopeProjectHtml(node) {
    var spec = scopeSpec(node);
    var fields = [
      '<div class="scope-field"><div class="k">Goal</div><p class="scope-value">' + htmlEscape(spec.goal || "unmeasured") + "</p></div>",
      '<div class="scope-field"><div class="k">Contributions</div>' + scopeList(spec.contributions) + "</div>",
    ];
    if (spec.out_of_scope) {
      fields.push('<div class="scope-field"><div class="k">Out of scope</div>' + scopeList(spec.out_of_scope) + "</div>");
    }
    fields.push('<div class="scope-field"><div class="k">Version</div><p class="scope-value">' + htmlEscape(node.version || "unmeasured") + "</p></div>");
    return [
      '<article class="scope-node scope-node-project" data-scope-node="' + htmlEscape(node.id) + '">',
      '<div class="k">Project</div>',
      "<h3>" + htmlEscape(node.id) + "</h3>",
      fields.join(""),
      "</article>",
    ].join("");
  }

  function scopeDirectionHtml(node, children) {
    var spec = scopeSpec(node);
    var metric = typeof spec.metric === "object" ? (spec.metric.name || JSON.stringify(spec.metric)) : spec.metric;
    var childHtml = children.length
      ? children.map(scopeTaskHtml).join("")
      : '<li class="scope-task-empty">No accepted validation Milestones under this Direction.</li>';
    return [
      '<article class="scope-node scope-node-direction" data-scope-node="' + htmlEscape(node.id) + '">',
      '<div class="scope-node-head">',
      '<div><div class="k">Direction</div><h3>' + htmlEscape(node.id) + "</h3></div>",
      '<span class="chip" data-status="' + htmlEscape(node.status || "unmeasured") + '">' + htmlEscape(node.status || "unmeasured") + "</span>",
      "</div>",
      '<p class="card-text"><b>Hypothesis:</b> ' + htmlEscape(spec.hypothesis || "unmeasured") + "</p>",
      '<div class="kv-grid">',
      '<div class="k">Metric</div><div>' + htmlEscape(metric || "unmeasured") + "</div>",
      '<div class="k">Success gate</div><div>' + htmlEscape(spec.success_gate || "unmeasured") + "</div>",
      '<div class="k">Version</div><div>' + htmlEscape(node.version || "unmeasured") + "</div>",
      "</div>",
      '<ol class="scope-task-list">' + childHtml + "</ol>",
      "</article>",
    ].join("");
  }

  function scopeTaskHtml(node) {
    var spec = scopeSpec(node);
    return [
      '<li class="scope-task" data-scope-node="' + htmlEscape(node.id) + '">',
      '<code>' + htmlEscape(node.id) + "</code>",
      '<p class="card-text"><b>Experiment:</b> ' + htmlEscape(spec.experiment || "not declared") + "</p>",
      '<p class="card-text"><b>Config:</b> ' + htmlEscape(spec.config || "not declared") + "</p>",
      '<p class="card-text"><b>Control mode:</b> ' + htmlEscape(spec.control_mode || "not declared") + "</p>",
      '<p class="card-text"><b>Gate:</b> ' + htmlEscape(spec.gate || "not declared") + "</p>",
      "</li>",
    ].join("");
  }

  function objectivePanelHtml() {
    // The objective is Scope SSOT-owned; the dashboard only projects it.
    var projection = scopeProjection();
    var project = Object.keys(projection).map(function (id) { return projection[id]; })
      .filter(function (node) { return node && node.level === "project"; })[0];
    if (!project) {
      return [
        '<section class="protocol-panel protocol-hero" data-panel="objective">',
        '<div class="k">Objective (Scope SSOT)</div>',
        '<p class="card-text">No committed Project node. Run <code>/research-onboard</code> to propose one.</p>',
        "</section>",
      ].join("");
    }
    return [
      '<section class="protocol-panel protocol-hero" data-panel="objective">',
      '<div class="k">Objective (Scope SSOT)</div>',
      scopeProjectHtml(project),
      '<p class="card-text"><a href="scope.html">Full scope tree →</a></p>',
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
      "</section>",
    ].join("");
  }

  function routesPanelHtml() {
    // Route enum + meanings are schema.js-owned; the dashboard only renders them.
    var meanings = window.NEXT_ROUTE_MEANING || {};
    var routes = window.NEXT_ROUTE || [];
    if (!routes.length) return "";
    return [
      '<section class="protocol-panel" data-panel="route-rules">',
      "<h2>Allowed Next Routes</h2>",
      '<div class="route-list">',
      routes.map(function (route) {
        return [
          '<article class="route-row" data-route="' + htmlEscape(route) + '">',
          "<code>" + htmlEscape(route) + "</code>",
          "<p>" + htmlEscape(meanings[route] || "") + "</p>",
          "</article>",
        ].join("");
      }).join(""),
      "</div>",
      "</section>",
    ].join("");
  }

  function protocolLinksHtml() {
    return [
      '<section class="protocol-panel" data-panel="protocol-links">',
      "<h2>Operating Protocols</h2>",
      '<p class="card-text">The dashboard owns no protocol prose. The owners:</p>',
      '<ul class="constraint-list">',
      '<li><code>workflow.ts</code> — the executable controller and evidence gates.</li>',
      '<li><code>CLAUDE.md</code> — the five universal protocols and agent rules.</li>',
      '<li><a href="rules/html-rules.html">html-rules.html</a> + <a href="rules/trustworthy-research-rules.html">trustworthy-research-rules.html</a> — the binding R/T rule corpus (mirrored in <code>data/rules.js</code>).</li>',
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

  function statusSchema() {
    return window.RESEARCH_STATUS_SCHEMA || {};
  }

  function statusFamily(status) {
    var map = window.RESEARCH_STATUS_FAMILY || {};
    return map[status] || "unknown";
  }

  function packageStatus(pkg) {
    return pkg && (pkg.status || pkg.workflowState) || "";
  }

  function statusPillHtml(pkg) {
    var s = packageStatus(pkg);
    var present = s !== "";
    var label = present ? s : "unmeasured";
    var family = present ? statusFamily(s) : "unknown";
    return [
      '<span class="chip chip-status status-' + htmlEscape(family) + '"',
      ' data-status="' + htmlEscape(label) + '"',
      ' data-status-family="' + htmlEscape(family) + '"',
      ' title="' + htmlEscape("(category=" + (pkg.category || "?") + ", status=" + label + ")") + '">',
      htmlEscape(label),
      "</span>",
    ].join("");
  }

  function missingRequiredFields(pkg) {
    var schema = statusSchema()[normalizeCategory(pkg.category)];
    if (!schema) return [];
    var status = packageStatus(pkg);
    var rules = schema.required || {};
    // The _all trio applies to every state except those listed in _all_exempt
    // (STOPPED is terminal-within-lane and only needs its own per-status fields).
    var exempt = (rules._all_exempt || []).indexOf(status) >= 0;
    var required = [].concat(!exempt && rules._all ? rules._all : []);
    if (status && rules[status]) {
      required = required.concat(rules[status]);
    }
    var missing = [];
    required.forEach(function (field) {
      var v = pkg[field];
      var present = false;
      if (Array.isArray(v)) {
        present = v.length > 0;
      } else if (v != null && String(v).trim() !== "") {
        present = true;
      }
      if (!present && missing.indexOf(field) === -1) missing.push(field);
    });
    return missing;
  }

  function missingFieldsChipHtml(pkg) {
    var missing = missingRequiredFields(pkg);
    if (!missing.length) return "";
    var title = "missing required: " + missing.join(", ");
    return '<span class="chip chip-warn" data-missing-required="' + htmlEscape(missing.join(",")) + '" title="' + htmlEscape(title) + '">⚠ ' + missing.length + ' missing</span>';
  }

  function methodsTriedRows(pkg) {
    return Array.isArray(pkg.methodsTried) ? pkg.methodsTried : [];
  }

  function verdictCounts(rows) {
    // EXPERIMENT_VERDICT values are SCREAMING_SNAKE (PASS/FAIL/INCONCLUSIVE/DIAGNOSTIC).
    var c = { PASS: 0, FAIL: 0, INCONCLUSIVE: 0, DIAGNOSTIC: 0 };
    rows.forEach(function (r) {
      var v = (r && r.verdict) ? String(r.verdict).toUpperCase() : "";
      if (c[v] != null) c[v] += 1;
    });
    return c;
  }

  function methodsTriedSummaryHtml(pkg, maxRows) {
    var rows = methodsTriedRows(pkg);
    if (!rows.length) {
      return '<div class="methods-tried-empty">' + unmeasuredHtml() + " methodsTried</div>";
    }
    var counts = verdictCounts(rows);
    var head = [
      '<div class="methods-tried-summary">',
      '<span class="chip chip-verdict-pass" data-verdict="PASS">PASS ' + counts.PASS + "</span>",
      '<span class="chip chip-verdict-fail" data-verdict="FAIL">FAIL ' + counts.FAIL + "</span>",
      '<span class="chip chip-verdict-inc" data-verdict="INCONCLUSIVE">INCONCLUSIVE ' + counts.INCONCLUSIVE + "</span>",
      '<span class="methods-tried-count">' + rows.length + " methods tried</span>",
      "</div>",
    ].join("");
    var limit = typeof maxRows === "number" ? maxRows : rows.length;
    var shown = rows.slice(0, limit);
    var list = [
      '<ul class="methods-tried-mini">',
      shown.map(function (r) {
        var v = (r && r.verdict) ? String(r.verdict).toUpperCase() : "unmeasured";
        return [
          '<li data-verdict="' + htmlEscape(v) + '">',
          '<span class="verdict-tag verdict-' + htmlEscape(v) + '">' + htmlEscape(v) + "</span>",
          '<span class="method-name">' + htmlEscape((r && r.method) || "unmeasured") + "</span>",
          "</li>",
        ].join("");
      }).join(""),
      rows.length > limit ? '<li class="more">+ ' + (rows.length - limit) + " more</li>" : "",
      "</ul>",
    ].join("");
    return head + list;
  }

  function postmortemTileHtml(pkg) {
    if (normalizeCategory(pkg.category) !== "fail") return "";
    return [
      '<div class="card-tile card-tile-postmortem" data-tile="postmortem">',
      '<div class="tile-label">Post-mortem</div>',
      '<p class="tile-message"><strong>Why ended:</strong> ' + fieldOrUnmeasured(pkg.terminationMessage) + "</p>",
      pkg.reopenTrigger ? '<p class="tile-meta"><strong>Reopen trigger:</strong> ' + htmlEscape(pkg.reopenTrigger) + "</p>" : "",
      methodsTriedSummaryHtml(pkg, 3),
      "</div>",
    ].join("");
  }

  function adoptionTileHtml(pkg) {
    if (normalizeCategory(pkg.category) !== "success") return "";
    return [
      '<div class="card-tile card-tile-adoption" data-tile="adoption">',
      '<div class="tile-label">Adoption</div>',
      '<p class="tile-message"><strong>Why kept:</strong> ' + fieldOrUnmeasured(pkg.terminationMessage) + "</p>",
      '<p class="tile-meta"><strong>Adopted into:</strong> ' + fieldOrUnmeasured(pkg.adoptionPath) + "</p>",
      pkg.supersededBy ? '<p class="tile-meta"><strong>Superseded by:</strong> ' + htmlEscape(pkg.supersededBy) + "</p>" : "",
      methodsTriedSummaryHtml(pkg, 3),
      "</div>",
    ].join("");
  }

  function terminalTileHtml(pkg) {
    // Brainstorm is no longer a package category, so no Direction tile is rendered
    // for packages; pre-package ideas live on the ideas-only brainstorm lane.
    return postmortemTileHtml(pkg) + adoptionTileHtml(pkg);
  }

  function lastUpdatedHtml(pkg) {
    var iso = pkg.lastUpdated;
    if (!iso) return unmeasuredHtml();
    return '<time data-field="last-updated" datetime="' + htmlEscape(iso) + '">' + htmlEscape(iso) + "</time>";
  }

  function packageCardHtml(pkg) {
    var status = packageStatus(pkg) || "unmeasured";
    var cat = normalizeCategory(pkg.category);
    var isTerminal = cat === "success" || cat === "fail";
    return [
      '<a class="package-card package-link-card" href="' + htmlEscape(relativeDetailPath(pkg)) + '"',
      ' data-package-id="' + htmlEscape(pkg.id) + '"',
      ' data-category="' + htmlEscape(cat) + '"',
      ' data-route="' + htmlEscape(pkg.nextRoute || "unmeasured") + '"',
      ' data-status="' + htmlEscape(status) + '"',
      ' data-status-family="' + htmlEscape(statusFamily(status)) + '"',
      ' data-workflow-state="' + htmlEscape(status) + '">',
      '<div class="card-top">',
      tagBadgeHtml(pkg),
      statusPillHtml(pkg),
      missingFieldsChipHtml(pkg),
      "</div>",
      '<div class="card-body">',
      '<h3 class="card-title">' + htmlEscape(pkg.name) + "</h3>",
      tagSummaryHtml(pkg),
      '<p class="card-text"><strong>Problem:</strong> ' + htmlEscape(pkg.problem) + "</p>",
      '<p class="card-text"><strong>Objective:</strong> ' + htmlEscape(pkg.objective) + "</p>",
      '<p class="card-text"><strong>Motivation:</strong> ' + htmlEscape(pkg.motivation) + "</p>",
      isTerminal ? terminalTileHtml(pkg) : "",
      cat === "in-progress" ? [
        '<p class="card-text card-strip"><span><strong>Gate:</strong> ' + fieldOrUnmeasured(pkg.activeGate) + "</span> ",
        '<span><strong>Metric vs gate:</strong> ' + fieldOrUnmeasured(pkg.primaryMetricVsGate) + "</span></p>",
      ].join("") : "",
      '<p class="card-text card-strip"><span><strong>Next route:</strong> ' + chipHtml("route", pkg.nextRoute) + "</span> ",
      '<span><strong>Updated:</strong> ' + lastUpdatedHtml(pkg) + "</span></p>",
      "</div>",
      "</a>",
    ].join("");
  }

  function renderCategoryPage() {
    var root = byId("category-package-root");
    if (!root || !window.RESEARCH_CATEGORY_ID) return;
    // Brainstorm lane is ideas-only (renderBrainstorms); it holds no packages.
    if (window.RESEARCH_CATEGORY_ID === "brainstorm") return;

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

  function brainstormCardHtml(idea) {
    // Link the card to its doc when the idea carries a detailPath; doc-less ideas render as a static article.
    var hasDoc = !!idea.detailPath;
    var open = hasDoc
      ? '<a class="package-card package-link-card brainstorm-idea" href="' + htmlEscape(relativeDetailPath(idea)) + '" data-brainstorm-id="' + htmlEscape(idea.id) + '">'
      : '<article class="package-card brainstorm-idea" data-brainstorm-id="' + htmlEscape(idea.id) + '">';
    var created = idea.created_at ? String(idea.created_at).slice(0, 10) : "";
    var refs = Array.isArray(idea.lit_refs) ? idea.lit_refs : [];
    var meta = [];
    if (idea.rough_metric) {
      meta.push(
        '<div class="bi-meta-row" data-field="rough-metric"><dt>Rough metric</dt>' +
        '<dd class="bi-metric">' + htmlEscape(idea.rough_metric) + "</dd></div>"
      );
    }
    meta.push(
      '<div class="bi-meta-row" data-field="grounding"><dt>Grounding</dt><dd>' +
      (refs.length
        ? htmlEscape(refs.join(" · "))
        : '<span class="bi-ungrounded">not grounded yet</span>') +
      "</dd></div>"
    );
    return [
      open,
      '<header class="bi-top">',
      '<span class="bi-kicker">Pre-package idea</span>',
      created ? '<time class="bi-date" datetime="' + htmlEscape(idea.created_at) + '">' + htmlEscape(created) + "</time>" : "",
      "</header>",
      '<div class="bi-body">',
      '<h3 class="bi-title">' + htmlEscape(idea.title || idea.id) + "</h3>",
      idea.idea ? '<p class="bi-idea">' + htmlEscape(idea.idea) + "</p>" : "",
      '<dl class="bi-meta">' + meta.join("") + "</dl>",
      "</div>",
      '<footer class="bi-foot">',
      '<span class="bi-id">' + htmlEscape(idea.id) + "</span>",
      hasDoc ? '<span class="bi-cta">Open idea &rarr;</span>' : '<span class="bi-stage">brainstorm lane</span>',
      "</footer>",
      hasDoc ? "</a>" : "</article>",
    ].join("");
  }

  // Composed empty / getting-started state for the ideas-only brainstorm lane.
  function brainstormEmptyHtml() {
    return [
      '<div class="bi-empty" data-section="getting-started">',
      "<h3>No ideas captured yet</h3>",
      "<p>This lane is for cheap, pre-package hunches &mdash; one sentence is enough. An idea earns its place if it names a concrete change and the rough metric you would expect to move.</p>",
      '<ul class="bi-empty-eg">',
      "<li><span>title</span>Share one RQ-VAE codebook across the video and text towers</li>",
      "<li><span>rough metric</span>R@1 +1.5 on MSR-VTT 1k-A, same codebook size</li>",
      "</ul>",
      '<p class="bi-empty-cmd">Capture the first one with <code>/research-brainstorm</code></p>',
      "</div>",
    ].join("");
  }

  // Brainstorm lane = pre-package ideas (not packages, not in the SSOT), read
  // from window.BRAINSTORMS (data/brainstorms.js). Managed by /research-brainstorm.
  function renderBrainstorms() {
    var root = byId("brainstorm-ideas-root");
    if (!root || window.RESEARCH_CATEGORY_ID !== "brainstorm") return;
    var ideas = window.BRAINSTORMS || [];
    // Ideas-only lane: renderCategoryPage() bails for brainstorm, so the masthead
    // lead + count would otherwise stay blank / "0 packages". Fill them here.
    var summary = byId("category-summary");
    if (summary && !summary.textContent.trim()) {
      summary.textContent = "Cheap, pre-package, pre-SSOT ideas live here. Each is a hunch worth a sentence — not a committed direction and not gated. Shape one with /research-brainstorm, then convert it through Triage into a ratified Direction with its own package.";
    }
    var laneCount = byId("category-count");
    if (laneCount) laneCount.textContent = ideas.length + " idea" + (ideas.length === 1 ? "" : "s");
    var count = byId("brainstorm-ideas-count");
    if (count) count.textContent = String(ideas.length) + " idea" + (ideas.length === 1 ? "" : "s");
    root.innerHTML = ideas.length
      ? ideas.map(brainstormCardHtml).join("")
      : brainstormEmptyHtml();
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
      '<a class="pill" href="' + rootPrefix() + 'categories/' + htmlEscape(pkg.category) + '/">Category</a>',
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
      '<div class="k">Next Route</div><div data-route>RUN_NEXT_EXPERIMENT | FIX_IMPLEMENTATION | REVISE_PLAN | TERMINATE | ASK_USER</div>',
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
      '<div class="notice">Evidence and resume are not separate modules. They are expressed as Continuity &amp; Verification in Overview, with exact source paths mirrored in <code>_agent/context.html</code>.</div>',
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
      '<a class="skip-link" href="#main-content">Skip to main content</a>',
      '<div class="shell page-grid">',
      '<nav class="side-nav" aria-label="Package modules">',
      '<div class="label">Package modules</div>',
      MODULES.map(function (item) {
        var aria = item.id === mod.id ? ' aria-current="page"' : "";
        return '<a href="' + modulePageHref(pkg, item.id) + '"' + aria + ">" + htmlEscape(item.title) + "</a>";
      }).join(""),
      "</nav>",
      '<main id="main-content">',
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
      '<article class="module-card" data-card="implementation-review"><h3>Implementation Review</h3><table class="data-table" data-table="implementation-review"><thead><tr><th>Change ID</th><th>Purpose</th><th>Unit</th><th>Owned Files</th><th>Reviewer Verdict</th><th>Finding Class</th><th>Required Fix</th><th>Main Decision</th><th>Validation</th></tr></thead><tbody><tr><td>change_id</td><td>purpose</td><td>unit</td><td>files</td><td>REVIEW_PASS|NEEDS_FIX|REVIEW_BLOCKED</td><td>BLOCKING|NON_BLOCKING|QUESTION|INVALID_FINDING</td><td>fix</td><td data-decision>Decision / Evidence Used</td><td>checks</td></tr></tbody></table></article>',
      '<article class="module-card" data-card="resource-allocation"><h3>Resource Allocation</h3><table class="data-table" data-table="resource-allocation"><thead><tr><th>Exp ID</th><th>Purpose</th><th>Dependency</th><th>Target</th><th>Capacity</th><th>Command/CWD/Env</th><th>Session/Job</th><th>Artifact Root</th><th>Log Path</th><th>Status</th></tr></thead><tbody><tr><td>exp_id</td><td>purpose</td><td>dependency</td><td>resource/job</td><td>live snapshot</td><td><code class="command">command</code></td><td>session</td><td>artifact root</td><td>log</td><td>QUEUED|RUNNING|COMPLETED|RUN_FAILED|RUN_HALTED</td></tr></tbody></table></article>',
      '<article class="module-card" data-card="latest-live-check"><h3>Latest Live Check</h3><table class="data-table" data-table="live-check"><thead><tr><th>Time</th><th>Exp ID</th><th>Run State</th><th>Progress</th><th>Latest Metrics</th><th>Resource Use</th><th>Artifact Status</th><th>ETA</th><th>Live Action</th><th>Next Check</th></tr></thead><tbody><tr><td>time</td><td>exp_id</td><td>RUNNING|STALE|COMPLETED</td><td>phase/epoch</td><td>objective metric only</td><td>resource/job</td><td>ok|missing</td><td>eta</td><td>CONTINUE_RUN|REPAIR|ASK_USER|ESCALATE</td><td>time</td></tr></tbody></table><p>Keep only the latest live check here. Detailed logs belong in artifacts.</p></article>',
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
      '<article class="module-card" data-card="result-gate"><h3>Result Gate</h3><table class="data-table" data-table="result-gate"><thead><tr><th>Exp ID</th><th>Validity</th><th>Baseline</th><th>PLAN Gate</th><th>Observed Metric</th><th>Budget/Resource Use</th><th>Seed Status</th><th>Artifact Completeness</th><th>Verdict</th><th>Reason</th></tr></thead><tbody><tr><td>exp_id</td><td>VALID|PARTIAL|RESULT_FAIL</td><td>baseline</td><td>gate</td><td>metric</td><td>budget</td><td>seed</td><td>artifacts</td><td data-decision>PASS|FAIL|INCONCLUSIVE|DIAGNOSTIC</td><td>reason</td></tr></tbody></table></article>',
      '<article class="module-card" data-card="artifact-verification"><h3>Artifact Verification</h3><div class="artifact-list"><div class="artifact-row"><div class="kind">primary artifact</div><code data-artifact="primary-artifact">artifacts/research/.../primary_output</code></div><div class="artifact-row"><div class="kind">log</div><code data-artifact="log">artifacts/research/.../logs/run.log</code></div><div class="artifact-row"><div class="kind">summary</div><code data-artifact="summary">artifacts/research/.../summaries/result.json</code></div></div><p>Before recording numbers, verify artifacts exist, match the experiment id/config, and were modified after launch.</p></article>',
      '<article class="module-card" data-card="analysis"><h3>Supported Claims</h3><p data-field="analysis">Concise interpretation tied to PLAN objective, gates, baseline, budget, seed status, and artifact completeness.</p></article>',
      '<article class="module-card" data-card="unsupported-claims"><h3>Unsupported Claims</h3><p data-field="unsupported-claims">List claims this result does not support, including metric, seed, budget, route, or rerank limitations.</p></article>',
      '<article class="module-card" data-card="next-action"><h3>Step 7 Next Action</h3><div class="kv-grid"><div class="k">Route</div><div data-route>RUN_NEXT_EXPERIMENT | FIX_IMPLEMENTATION | REVISE_PLAN | TERMINATE | ASK_USER</div><div class="k">Reason</div><div data-field="next-action-reason">Apply PLAN gates to verified evidence.</div><div class="k">Decision</div><div data-decision>Decision / Evidence Used</div></div></article>',
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

  // Page slugs match the physical filenames created by create_research_package.py
  // (Python is authoritative). The landing page slug is "index" (index.html), not
  // "overview". Brainstorm is not a stage page (the brainstorm lane is ideas-only).
  var STAGE_PAGES = [
    { slug: "index", label: "Overview", href: "index.html" },
    { slug: "plan", label: "Plan", href: "plan.html" },
    { slug: "implementation", label: "Implementation", href: "implementation.html" },
    { slug: "results", label: "Results", href: "results.html" },
    { slug: "analysis", label: "Analysis", href: "analysis.html" },
    { slug: "tracker", label: "Tracker", href: "tracker.html" },
    { slug: "docs", label: "Docs", href: "docs/" },
  ];

  var ALWAYS_PRESENT_PAGES = ["index", "tracker", "docs"];

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
      statusStripCellHtml("State", "workflow-state", packageStatus(pkg), { dataset: "workflow-state" }),
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
    var prefix = packagePrefix();
    var current = document.body ? document.body.getAttribute("data-page") : null;
    var html = STAGE_PAGES.map(function (p) {
      var isPresent = present.indexOf(p.slug) >= 0 || ALWAYS_PRESENT_PAGES.indexOf(p.slug) >= 0;
      var href = prefix + p.href;
      var aria = p.slug === current ? ' aria-current="page"' : "";
      if (isPresent) {
        return '<a class="package-nav-link" href="' + htmlEscape(href) + '" data-page-link="' + p.slug + '"' + aria + ">" + htmlEscape(p.label) + "</a>";
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
      ["workflow-state", packageStatus(pkg)],
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
    // RESULT_VALIDITY buckets (SCREAMING_SNAKE data-validity values).
    var counts = { VALID: 0, PARTIAL: 0, RESULT_FAIL: 0, UNMEASURED: 0, DIAGNOSTIC_ONLY: 0, MISSING: 0 };
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
      var status = e && e.status ? String(e.status) : "QUEUED";
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

  function buildPackageFilterForm(form, lanes, routes, statuses) {
    // brainstorm + in-progress default to checked (the two active lanes the
    // user typically wants on load); success + fail default to unchecked.
    var DEFAULT_ON = { brainstorm: true, "in-progress": true };
    var laneCheckboxes = lanes.map(function (id) {
      var checked = DEFAULT_ON[id] ? " checked" : "";
      return '<label><input type="checkbox" name="lane" value="' + htmlEscape(id) + '"' + checked + "> " + htmlEscape(id) + "</label>";
    }).join(" ");
    var routeOptions = ['<option value="all">All routes</option>'].concat(routes.map(function (r) {
      return '<option value="' + htmlEscape(r) + '">' + htmlEscape(r) + "</option>";
    })).join("");
    var statusOptions = ['<option value="all">All statuses</option>'].concat(statuses.map(function (s) {
      return '<option value="' + htmlEscape(s) + '">' + htmlEscape(s) + "</option>";
    })).join("");
    form.innerHTML = [
      '<fieldset class="filter-group"><legend>Lane</legend>' + laneCheckboxes + "</fieldset>",
      '<fieldset class="filter-group"><legend>Status</legend><select name="status">' + statusOptions + "</select></fieldset>",
      '<fieldset class="filter-group"><legend>Next route</legend><select name="route">' + routeOptions + "</select></fieldset>",
      '<fieldset class="filter-group"><legend>Sort</legend><select name="sort"><option value="recency">Most recent</option><option value="category">By lane</option><option value="status">By status</option></select></fieldset>',
      '<fieldset class="filter-group filter-meta"><legend>Quality</legend><label><input type="checkbox" name="show-only-missing"> only ⚠ missing-required</label></fieldset>',
    ].join("");
  }

  function paintDashboardPackages(form, root) {
    var lanes = form ? Array.prototype.map.call(form.querySelectorAll('input[name="lane"]:checked'), function (i) { return i.value; }) : [];
    var route = form && form.elements.route ? form.elements.route.value : "all";
    var statusFilter = form && form.elements.status ? form.elements.status.value : "all";
    var onlyMissing = form && form.elements["show-only-missing"] ? form.elements["show-only-missing"].checked : false;
    var sort = form && form.elements.sort ? form.elements.sort.value : "recency";
    // Lane filter is always required: no lane selected → no packages rendered.
    var items = (lanes && lanes.length)
      ? packages().filter(function (p) { return lanes.indexOf(normalizeCategory(p.category)) >= 0; })
      : [];
    if (route !== "all") items = items.filter(function (p) { return (p.nextRoute || "unmeasured") === route; });
    if (statusFilter !== "all") items = items.filter(function (p) { return (packageStatus(p) || "unmeasured") === statusFilter; });
    if (onlyMissing) items = items.filter(function (p) { return missingRequiredFields(p).length > 0; });
    if (sort === "recency") {
      items.sort(function (a, b) { return String(b.lastUpdated || "").localeCompare(String(a.lastUpdated || "")); });
    } else if (sort === "status") {
      items.sort(function (a, b) { return String(packageStatus(a)).localeCompare(String(packageStatus(b))); });
    } else {
      items.sort(function (a, b) { return String(a.category).localeCompare(String(b.category)); });
    }
    var emptyMessage = (!lanes || lanes.length === 0)
      ? 'Select a lane above (brain-storm / in-progress / success / fail) to list packages.'
      : 'No packages match the current filters.';
    root.innerHTML = items.length
      ? items.map(packageCardHtml).join("")
      : '<div class="empty-state">' + emptyMessage + "</div>";
  }

  function renderDashboardPackages() {
    var root = byId("dashboard-package-root");
    if (!root) return;
    var form = document.querySelector('[data-card="package-filters"]');
    // Lanes always list all 4 categories (brainstorm / in-progress / success / fail),
    // regardless of which currently have packages — so the user knows every option.
    var lanes = categories().map(function (c) { return c.id; });
    if (!lanes.length) {
      lanes = distinctSorted(packages().map(function (p) { return normalizeCategory(p.category); }));
    }
    var routes = distinctSorted(packages().map(function (p) { return p.nextRoute || "unmeasured"; }));
    var statuses = distinctSorted(packages().map(function (p) { return packageStatus(p) || "unmeasured"; }));
    if (form && form.dataset.bound !== "1") {
      form.dataset.bound = "1";
      buildPackageFilterForm(form, lanes, routes, statuses);
      form.addEventListener("change", function () { paintDashboardPackages(form, root); });
    }
    paintDashboardPackages(form, root);
  }

  function contributionSpineLookup() {
    var list = window.RESEARCH_CONTRIBUTION_SPINE || [];
    var map = {};
    list.forEach(function (item) { map[item.id] = item.label; });
    return map;
  }

  function groupBy(items, keyFn) {
    var groups = {};
    items.forEach(function (item) {
      var k = keyFn(item) || "(unmeasured)";
      if (!groups[k]) groups[k] = [];
      groups[k].push(item);
    });
    return groups;
  }

  function methodsTriedTableHtml(pkg) {
    var rows = methodsTriedRows(pkg);
    if (!rows.length) return '<p class="lead">' + unmeasuredHtml() + " methodsTried for this package.</p>";
    return [
      '<table class="data-table methods-tried-table" data-table="methods-tried">',
      "<thead><tr>",
      "<th>Method</th><th>Hypothesis</th><th>Gate</th><th>Measured</th><th>Verdict</th><th>Evidence</th>",
      "</tr></thead>",
      "<tbody>",
      rows.map(function (r) {
        var v = (r && r.verdict) ? String(r.verdict).toUpperCase() : "unmeasured";
        var ev = r && r.evidencePath ? '<code>' + htmlEscape(r.evidencePath) + '</code>' : unmeasuredHtml();
        return [
          '<tr data-verdict="' + htmlEscape(v) + '">',
          "<td>" + htmlEscape((r && r.method) || "unmeasured") + "</td>",
          "<td>" + htmlEscape((r && r.hypothesis) || "unmeasured") + "</td>",
          "<td>" + htmlEscape((r && r.gate) || "unmeasured") + "</td>",
          "<td>" + htmlEscape((r && r.measured) || "unmeasured") + "</td>",
          '<td><span class="verdict-tag verdict-' + htmlEscape(v) + '">' + htmlEscape(v) + "</span></td>",
          "<td>" + ev + "</td>",
          "</tr>",
        ].join("");
      }).join(""),
      "</tbody></table>",
    ].join("");
  }

  function learningsPackageBlock(pkg, opts) {
    opts = opts || {};
    var status = packageStatus(pkg) || "unmeasured";
    var spineMap = contributionSpineLookup();
    var spineLabel = spineMap[pkg.contributionSpineFlag] || pkg.contributionSpineFlag || "unmeasured";
    var extras = [];
    if (pkg.adoptionPath) extras.push("<strong>Adopted into:</strong> " + htmlEscape(pkg.adoptionPath));
    if (pkg.supersededBy) extras.push("<strong>Superseded by:</strong> " + htmlEscape(pkg.supersededBy));
    if (pkg.reopenTrigger) extras.push("<strong>Reopen trigger:</strong> " + htmlEscape(pkg.reopenTrigger));
    if (pkg.promotedTo) extras.push("<strong>Promoted to:</strong> " + htmlEscape(pkg.promotedTo));
    return [
      '<article class="learnings-package" data-package-id="' + htmlEscape(pkg.id) + '" data-status="' + htmlEscape(status) + '">',
      '<header class="learnings-package-head">',
      '<h3><a href="' + relativeDetailPath(pkg) + '">' + htmlEscape(pkg.name) + "</a></h3>",
      statusPillHtml(pkg),
      '<span class="chip chip-spine" data-spine="' + htmlEscape(pkg.contributionSpineFlag || "unmeasured") + '">' + htmlEscape(spineLabel) + "</span>",
      "</header>",
      '<p class="learnings-message"><strong>Why ' + (opts.kind === "fail" ? "ended" : "kept") + ":</strong> " + fieldOrUnmeasured(pkg.terminationMessage) + "</p>",
      extras.length ? '<p class="learnings-meta">' + extras.join(" · ") + "</p>" : "",
      methodsTriedTableHtml(pkg),
      "</article>",
    ].join("");
  }

  function learningsGroupHtml(title, items, opts) {
    if (!items.length) {
      return [
        '<section class="learnings-group learnings-group-empty" data-group="' + htmlEscape(opts.id) + '">',
        "<h2>" + htmlEscape(title) + "</h2>",
        '<p class="empty-state">No packages in this group.</p>',
        "</section>",
      ].join("");
    }
    var spineMap = contributionSpineLookup();
    var bySpine = groupBy(items, function (p) { return p.contributionSpineFlag || "unmeasured"; });
    var spineKeys = Object.keys(bySpine).sort();
    return [
      '<section class="learnings-group" data-group="' + htmlEscape(opts.id) + '">',
      "<h2>" + htmlEscape(title) + ' <span class="count">(' + items.length + ")</span></h2>",
      spineKeys.map(function (spineId) {
        var label = spineMap[spineId] || spineId;
        return [
          '<details class="learnings-spine-block" data-spine="' + htmlEscape(spineId) + '" open>',
          '<summary><strong>' + htmlEscape(label) + '</strong> <span class="count">(' + bySpine[spineId].length + ")</span></summary>",
          bySpine[spineId].map(function (p) { return learningsPackageBlock(p, opts); }).join(""),
          "</details>",
        ].join("");
      }).join(""),
      "</section>",
    ].join("");
  }

  function learningsHeroHtml(pkgs) {
    var counts = { adopted: 0, pending: 0, superseded: 0, archived: 0, reopenable: 0 };
    pkgs.forEach(function (p) {
      var s = packageStatus(p);
      if (s === "ADOPTED") counts.adopted += 1;
      else if (s === "ADOPTED_UNCONFIRMED") counts.pending += 1;
      else if (s === "WIN_SUPERSEDED") counts.superseded += 1;
      else if (s === "ARCHIVED") counts.archived += 1;
      else if (s === "ARCHIVED_CONDITIONAL") counts.reopenable += 1;
    });
    return [
      '<section class="learnings-hero" data-card="learnings-hero">',
      '<div class="k">Cross-package learnings</div>',
      "<h2>What this project has actually tried</h2>",
      '<p class="lead">A derived view over <code>data/research-packages.js</code>. Adopted wins and failed attempts grouped by which paper-spine contribution they touch, so the agent reads the full <em>what was tried, what worked, why it failed</em> picture in one pass.</p>',
      '<div class="learnings-stat-grid">',
      '<div class="stat-cell"><div class="k">Adopted</div><div class="v">' + counts.adopted + "</div></div>",
      '<div class="stat-cell"><div class="k">Pending ack</div><div class="v">' + counts.pending + "</div></div>",
      '<div class="stat-cell"><div class="k">Superseded</div><div class="v">' + counts.superseded + "</div></div>",
      '<div class="stat-cell"><div class="k">Archived (fail)</div><div class="v">' + counts.archived + "</div></div>",
      '<div class="stat-cell"><div class="k">Archived · conditional</div><div class="v">' + counts.reopenable + "</div></div>",
      "</div>",
      "</section>",
    ].join("");
  }

  function renderLearningsView() {
    var root = byId("learnings-root");
    if (!root) return;
    var all = packages().slice();
    var adopted = all.filter(function (p) {
      var s = packageStatus(p);
      return s === "ADOPTED" || s === "ADOPTED_UNCONFIRMED" || s === "WIN_SUPERSEDED";
    });
    var failed = all.filter(function (p) {
      var s = packageStatus(p);
      return s === "ARCHIVED" || s === "ARCHIVED_CONDITIONAL";
    });
    var reopenable = all.filter(function (p) { return packageStatus(p) === "ARCHIVED_CONDITIONAL"; });
    root.innerHTML = [
      learningsHeroHtml(all),
      learningsGroupHtml("Adopted wins", adopted, { id: "adopted", kind: "success" }),
      learningsGroupHtml("Failed attempts", failed, { id: "failed", kind: "fail" }),
      learningsGroupHtml("Conditional archive", reopenable, { id: "reopenable", kind: "fail" }),
    ].join("");
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

  function parseNumericCell(text) {
    if (text == null) return NaN;
    var s = String(text).replace(/−/g, "-").replace(/,/g, "");
    var m = s.match(/-?\d+(?:\.\d+)?/);
    return m ? parseFloat(m[0]) : NaN;
  }

  function tableIsSortable(table) {
    if (table.getAttribute("data-sortable") === "false") return false;
    if (table.querySelector("td[rowspan], th[rowspan]")) return false;
    if (!table.tHead || !table.tBodies || !table.tBodies[0]) return false;
    return true;
  }

  function sortTableByColumn(table, colIdx, dir) {
    var tbody = table.tBodies[0];
    var rows = Array.prototype.slice.call(tbody.rows);
    rows.forEach(function (r, i) {
      if (r.getAttribute("data-orig-idx") == null) r.setAttribute("data-orig-idx", i);
    });
    var numericCount = 0;
    var values = rows.map(function (r) {
      var cell = r.cells[colIdx];
      var txt = cell ? cell.textContent.trim() : "";
      var n = parseNumericCell(txt);
      if (!isNaN(n)) numericCount++;
      return { row: r, text: txt, num: n };
    });
    var allNumeric = numericCount > 0 && numericCount === values.length;
    values.sort(function (a, b) {
      var cmp;
      if (allNumeric) {
        cmp = a.num - b.num;
      } else {
        var an = isNaN(a.num), bn = isNaN(b.num);
        if (an && !bn) cmp = 1;
        else if (!an && bn) cmp = -1;
        else cmp = a.text.localeCompare(b.text, undefined, { numeric: true });
      }
      if (cmp === 0) {
        cmp = parseInt(a.row.getAttribute("data-orig-idx"), 10)
            - parseInt(b.row.getAttribute("data-orig-idx"), 10);
      }
      return dir === "descending" ? -cmp : cmp;
    });
    var frag = document.createDocumentFragment();
    values.forEach(function (v) { frag.appendChild(v.row); });
    tbody.appendChild(frag);
  }

  function enhanceSortableTables(root) {
    var scope = root || document;
    var tables = scope.querySelectorAll("table.data-table");
    Array.prototype.forEach.call(tables, function (table) {
      if (table.getAttribute("data-sort-enhanced") === "1") return;
      if (!tableIsSortable(table)) return;
      var ths = table.tHead.rows[0] ? table.tHead.rows[0].cells : [];
      Array.prototype.forEach.call(ths, function (th, idx) {
        if (th.getAttribute("data-sort") === "off") return;
        th.classList.add("data-table-sort");
        th.setAttribute("aria-sort", "none");
        th.setAttribute("tabindex", "0");
        var onActivate = function () {
          var cur = th.getAttribute("aria-sort");
          var next = cur === "ascending" ? "descending" : "ascending";
          Array.prototype.forEach.call(ths, function (other) {
            if (other !== th && other.classList.contains("data-table-sort")) {
              other.setAttribute("aria-sort", "none");
            }
          });
          th.setAttribute("aria-sort", next);
          sortTableByColumn(table, idx, next);
        };
        th.addEventListener("click", onActivate);
        th.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onActivate();
          }
        });
      });
      table.setAttribute("data-sort-enhanced", "1");
    });
  }

  // ============================================================
  // Per-page canon painters (HTML design spec 2026-05-24).
  // Each painter is a graceful no-op when its host element or its
  // backing inventory field is absent — the static template renders
  // a usable placeholder otherwise.
  // ============================================================

  function renderUserZoneIdentity() {
    var pkg = currentPackage();
    if (!pkg) return;
    var map = {
      "problem-tldr": pkg.problemTldr,
      "objective-tldr": pkg.objectiveTldr,
      "motivation-tldr": pkg.motivationTldr,
    };
    Object.keys(map).forEach(function (field) {
      var v = map[field];
      if (v == null) return;
      var node = document.querySelector('[data-card="identity-tldr"] [data-field="' + field + '"] .identity-tldr-v');
      if (node) node.textContent = String(v);
    });
  }

  function renderHeadline() {
    var card = document.querySelector('[data-card="headline"]');
    if (!card) return;
    var pkg = currentPackage();
    if (!pkg || !pkg.headline) return;
    var h = pkg.headline;
    var kind = String(h.kind || "freeform");
    card.setAttribute("data-headline-kind", kind);
    var title = card.querySelector('[data-field="headline-title"]');
    if (title) title.textContent = String(h.name || "Headline");
    var body = card.querySelector('[data-block="headline-body"]');
    if (!body) return;
    var html = "";
    if (kind === "metric") {
      html = '<p class="card-text"><b>' + htmlEscape(h.metricLabel || "Metric") + ":</b> " +
             '<span class="num">' + htmlEscape(h.value || "unmeasured") + "</span>" +
             (h.evidencePath ? ' &middot; <code>' + htmlEscape(h.evidencePath) + "</code>" : "") + "</p>";
    } else if (kind === "baseline") {
      var rows = Array.isArray(h.baselines) ? h.baselines : [];
      html = "<ul>" + rows.map(function (b) {
        return "<li><code>" + htmlEscape(b.id || "baseline") + "</code> &mdash; " +
               htmlEscape(b.note || "unmeasured") + "</li>";
      }).join("") + "</ul>";
    } else if (kind === "evaluation" || kind === "infrastructure") {
      html = '<p class="card-text">' + htmlEscape(h.summary || "unmeasured") + "</p>";
    } else {
      html = '<p class="card-text">' + htmlEscape(h.text || h.summary || "unmeasured") + "</p>";
    }
    body.innerHTML = html;
  }

  function renderKeyInsight() {
    var card = document.querySelector('[data-card="key-insight"]');
    if (!card) return;
    var pkg = currentPackage();
    var v = pkg && pkg.keyInsight ? String(pkg.keyInsight).trim() : "";
    if (!v) {
      card.setAttribute("data-empty", "true");
      card.setAttribute("hidden", "");
      return;
    }
    card.removeAttribute("hidden");
    card.setAttribute("data-empty", "false");
    var slot = card.querySelector('[data-field="key-insight"]');
    if (slot) slot.textContent = v;
  }

  function renderObjectiveContract() {
    var card = document.querySelector('[data-card="plan-invariants"]');
    if (!card) return;
    var pkg = currentPackage();
    if (!pkg || !pkg.objectiveContract) return;
    var c = pkg.objectiveContract;
    var map = {
      "hypothesis-one-line": c.hypothesisOneLine,
      "metric-one-line": c.metric,
      "baseline-one-line": c.baseline,
      "budget-one-line": c.budget,
      "success-predicate": c.successPredicate,
    };
    Object.keys(map).forEach(function (field) {
      if (map[field] == null) return;
      var node = card.querySelector('[data-field="' + field + '"] .invariant-v');
      if (node) node.textContent = String(map[field]);
    });
  }

  function computeNextUp(exps) {
    if (!Array.isArray(exps) || !exps.length) return { nextEligible: null, runningNow: null };
    var byId = {};
    exps.forEach(function (e) { if (e && e.id) byId[e.id] = e; });
    var running = exps.filter(function (e) { return e && e.status === "RUNNING"; }).map(function (e) { return e.id; });
    var next = null;
    for (var i = 0; i < exps.length; i++) {
      var e = exps[i];
      if (!e || e.status !== "QUEUED") continue;
      var after = Array.isArray(e.after) ? e.after : [];
      var depsDone = after.every(function (d) {
        var dep = byId[d];
        return dep && (dep.status === "COMPLETED" || dep.status === "SKIPPED");
      });
      if (depsDone) { next = e.id; break; }
    }
    return { nextEligible: next, runningNow: running.length ? running.join(", ") : null };
  }

  function renderPipelineTimeline() {
    var host = document.querySelector('[data-card="pipeline-timeline"] [data-field="pipeline-timeline-list"]');
    if (!host) return;
    var pkg = currentPackage();
    var exps = pkg && Array.isArray(pkg.experiments) ? pkg.experiments : [];
    var banner = document.querySelector('[data-card="pipeline-timeline"] [data-field="pipeline-next-up"]');
    if (banner) {
      var nu = computeNextUp(exps);
      banner.innerHTML = "<em>Next eligible: " + htmlEscape(nu.nextEligible || "none") + "</em>" +
                        (nu.runningNow ? " &middot; <em>Running now: " + htmlEscape(nu.runningNow) + "</em>" : "");
    }
    if (!exps.length) {
      host.innerHTML = '<li class="empty-state">No experiments in inventory.</li>';
      return;
    }
    host.innerHTML = exps.map(function (e) {
      var id = e && e.id ? String(e.id) : "unmeasured";
      var label = e && e.label ? String(e.label) : "";
      var status = e && e.status ? String(e.status) : "QUEUED";
      var purpose = e && e.purpose ? String(e.purpose) : "unmeasured";
      var output = e && e.output ? String(e.output) : "unmeasured";
      var gate = e && (e.gatePredicate || e.gate) ? String(e.gatePredicate || e.gate) : "unmeasured";
      var after = Array.isArray(e && e.after) ? e.after : [];
      var locked = e && e.lockedAt ? true : false;
      var hasEvidence = e && e.gateEvidence && e.gateEvidence.artifactPath;
      var docsAnchor = e && e.docsAnchor ? String(e.docsAnchor) : ("docs/pipeline.html#" + id.toLowerCase());
      var threadLinks = ['<a href="tracker.html#todo">tracker</a>'];
      if (!e || e.measures !== false) {
        threadLinks.push('<a href="results.html#result-slot-' + htmlEscape(id.toLowerCase()) + '">result</a>');
      }
      if (e && e.requiresCode) {
        threadLinks.push('<a href="implementation.html#changes">impl</a>');
      }
      if (e && (e.complex || e.docsAnchor)) {
        threadLinks.push('<a href="' + htmlEscape(docsAnchor) + '">docs</a>');
      }
      return [
        '<li class="pipeline-node" data-phase-id="' + htmlEscape(id) + '" data-phase-status="' + htmlEscape(status) + '">',
        '<div class="pipeline-node-head">',
        '<code class="phase-id">' + htmlEscape(id) + "</code>",
        label ? '<span class="pipeline-node-title">' + htmlEscape(label) + "</span>" : "",
        '<span class="chip" data-status="' + htmlEscape(status) + '">' + htmlEscape(status) + "</span>",
        hasEvidence ? '<span class="chip" title="' + htmlEscape(e.gateEvidence.artifactPath) + '">&#9989; evidence</span>' : "",
        locked ? '<span class="chip">&#128274; locked</span>' : "",
        "</div>",
        '<dl class="pipeline-node-fields">',
        '<dt>Purpose</dt><dd>' + htmlEscape(purpose) + "</dd>",
        '<dt>After</dt><dd>' + (after.length ? after.map(htmlEscape).join(", ") : "<em>none</em>") + "</dd>",
        '<dt>Output</dt><dd><code>' + htmlEscape(output) + "</code></dd>",
        '<dt>Gate</dt><dd>' + htmlEscape(gate) + "</dd>",
        "</dl>",
        '<nav class="pipeline-thread-links" aria-label="Task thread links">' + threadLinks.join("") + "</nav>",
        '<a class="pipeline-node-doc" href="' + htmlEscape(docsAnchor) + '">' + htmlEscape(docsAnchor) + "</a>",
        "</li>",
      ].join("");
    }).join("");
  }

  function renderImplementationPhaseStrip() {
    var host = document.querySelector('[data-card="phase-strip"] [data-list="phase-strip"]');
    if (!host) return;
    var pkg = currentPackage();
    var exps = pkg && Array.isArray(pkg.experiments) ? pkg.experiments : [];
    var changes = pkg && pkg.implementation && Array.isArray(pkg.implementation.changes) ? pkg.implementation.changes : [];
    if (!exps.length) {
      host.innerHTML = '<li class="empty-state">No experiments in inventory.</li>';
      return;
    }
    var byPhase = {};
    changes.forEach(function (c, idx) {
      var ids = Array.isArray(c && c.phaseIds) ? c.phaseIds : [];
      ids.forEach(function (p) {
        if (!byPhase[p]) byPhase[p] = [];
        byPhase[p].push(idx + 1);
      });
    });
    host.innerHTML = exps.map(function (e) {
      var id = e && e.id ? String(e.id) : "unmeasured";
      var status = e && e.status ? String(e.status) : "QUEUED";
      var nums = byPhase[id] || [];
      var reuse = nums.length === 0 ? "true" : "false";
      var nlabel = nums.length ? nums.join("+") : "&mdash;";
      return [
        '<li class="phase-strip-cell"',
        ' data-phase-id="' + htmlEscape(id) + '"',
        ' data-phase-status="' + htmlEscape(status) + '"',
        ' data-reuse-only="' + reuse + '">',
        '<code>' + htmlEscape(id) + "</code>",
        '<span class="phase-strip-changes">' + nlabel + "</span>",
        '<span class="chip" data-status="' + htmlEscape(status) + '">' + htmlEscape(status) + "</span>",
        "</li>",
      ].join("");
    }).join("");
  }

  var PSEUDO_TOKEN_RE = /(#[^\n]*)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(\b\d+(?:\.\d+)?\b)|(\b(?:if|else|elif|for|while|def|return|import|from|as|in|with|class|try|except|finally|raise|pass|break|continue|lambda|yield|and|or|not|True|False|None)\b)|(--?[A-Za-z][\w-]*)/g;

  function tokenizePseudoCode(src) {
    return String(src == null ? "" : src).replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    }).replace(PSEUDO_TOKEN_RE, function (_, comment, str, num, kw, flag) {
      if (comment) return '<span class="tok-comment">' + comment + "</span>";
      if (str)     return '<span class="tok-string">' + str + "</span>";
      if (num)     return '<span class="tok-number">' + num + "</span>";
      if (kw)      return '<span class="tok-keyword">' + kw + "</span>";
      if (flag)    return '<span class="tok-flag">' + flag + "</span>";
      return "";
    });
  }

  function rollupTestState(tests) {
    // Change-block test.state input values use the EXPERIMENT_VERDICT vocabulary
    // (PASS/FAIL/NOT_APPLICABLE); "pending" is a test-not-yet-run state.
    if (!Array.isArray(tests) || !tests.length) return { state: "pending", text: "0 tests" };
    var pass = 0, fail = 0, pending = 0, na = 0;
    tests.forEach(function (t) {
      var s = t && t.state ? String(t.state).toUpperCase() : "PENDING";
      if (s === "PASS") pass++;
      else if (s === "FAIL") fail++;
      else if (s === "NOT_APPLICABLE") na++;
      else pending++;
    });
    var state = fail ? "fail" : (pending ? (pass ? "partial" : "pending") : (pass ? "pass" : "pending"));
    var icon = state === "pass" ? "&#128994;" : state === "fail" ? "&#128308;" : state === "partial" ? "&#128992;" : "&#9675;";
    return { state: state, text: icon + " " + pass + " pass &middot; " + pending + " pending" + (fail ? " &middot; " + fail + " fail" : "") };
  }

  function changeTestsTodoHtml(tests) {
    if (!Array.isArray(tests) || !tests.length) {
      return '<li class="test-row" data-state="PENDING"><span class="test-state-icon">&#9675;</span> <em>no tests declared</em></li>';
    }
    var icons = { PASS: "&#9989;", FAIL: "&#10060;", PENDING: "&#9675;", NOT_APPLICABLE: "&oslash;" };
    return tests.map(function (t) {
      var s = t && t.state ? String(t.state).toUpperCase() : "PENDING";
      var id = t && t.testId ? String(t.testId) : "test-id";
      var note = t && t.note ? String(t.note) : "";
      var ev = t && t.evidencePath ? String(t.evidencePath) : "";
      return '<li class="test-row" data-state="' + htmlEscape(s) + '">' +
             '<span class="test-state-icon">' + (icons[s] || icons.PENDING) + "</span> " +
             '<code>' + htmlEscape(id) + "</code>" +
             (note ? " &mdash; " + htmlEscape(note) : "") +
             (ev ? ' &middot; <code>' + htmlEscape(ev) + "</code>" : "") +
             "</li>";
    }).join("");
  }

  function renderImplementationChanges() {
    var host = document.querySelector('[data-list="change-blocks"]');
    if (!host) return;
    var pkg = currentPackage();
    var changes = pkg && pkg.implementation && Array.isArray(pkg.implementation.changes) ? pkg.implementation.changes : [];
    if (!changes.length) return;
    var h2 = host.querySelector("h2.section-h2");
    host.innerHTML = (h2 ? h2.outerHTML : "<h2 class=\"section-h2\">Change blocks</h2>") + changes.map(function (c, i) {
      var id = c && c.id ? String(c.id) : "change-" + (i + 1);
      var title = c && c.title ? String(c.title) : "unmeasured";
      var critical = c && c.critical === true;
      var reason = c && c.criticalReason ? String(c.criticalReason) : "wiring";
      var summary = c && (critical ? c.blockSummary : c.oneLineSummary) || "unmeasured";
      var serves = Array.isArray(c && c.phaseIds) ? c.phaseIds : [];
      var rollup = rollupTestState(c && c.tests);
      var locked = c && c.lockedAt ? true : false;
      var pseudo = c && c.pseudoCode ? String(c.pseudoCode) : "";
      var firstLine = pseudo.split("\n")[0] || "";
      var fnameMatch = firstLine.match(/^#\s*([\w./-]+\.[a-z]+)/);
      var fname = fnameMatch ? fnameMatch[1] : "code";
      return [
        '<article class="change-block module-card" data-change-id="' + htmlEscape(id) + '" data-critical="' + (critical ? "true" : "false") + '" data-critical-reason="' + htmlEscape(reason) + '">',
        '<header class="change-block-header">',
        "<h3>" + htmlEscape(title) + "</h3>",
        '<div class="change-chips">',
        '<span class="chip change-chip change-chip-critical" data-critical="' + (critical ? "true" : "false") + '">' + (critical ? "critical &middot; " + htmlEscape(reason) : "wiring") + "</span>",
        '<span class="chip change-chip change-chip-rollup" data-rollup="' + htmlEscape(rollup.state) + '">' + rollup.text + "</span>",
        locked ? '<span class="chip change-chip change-chip-lock">&#128274; locked</span>' : "",
        "</div>",
        "</header>",
        '<p class="change-serves"><strong>serves:</strong> ' + (serves.length ? serves.map(function (p) {
          return '<a href="plan.html#' + htmlEscape(p) + '"><code>' + htmlEscape(p) + "</code></a>";
        }).join(" &middot; ") : "<em>no phases declared</em>") + "</p>",
        '<p class="change-summary">' + htmlEscape(summary) + "</p>",
        pseudo ? ([
          '<details class="change-pseudo-details"><summary>Pseudo-code</summary>',
          '<div class="pseudo-block">',
          '<header class="pseudo-block-header">',
          '<span class="pseudo-dot pseudo-dot--r"></span>',
          '<span class="pseudo-dot pseudo-dot--y"></span>',
          '<span class="pseudo-dot pseudo-dot--g"></span>',
          '<span class="pseudo-filename">' + htmlEscape(fname) + "</span>",
          "</header>",
          '<pre class="pseudo-body"><code>' + tokenizePseudoCode(pseudo) + "</code></pre>",
          "</div></details>",
        ].join("")) : "",
        '<details class="change-tests-details"><summary>Test todo</summary>',
        '<ol class="test-rows">' + changeTestsTodoHtml(c && c.tests) + "</ol>",
        "</details>",
        "</article>",
      ].join("");
    }).join("");
  }

  function renderImplementationAdjudication() {
    var card = document.querySelector('[data-card="adjudication"]');
    if (!card) return;
    var pkg = currentPackage();
    var a = pkg && pkg.implementation && pkg.implementation.adjudication;
    if (!a) return;
    var map = {
      "main-decision": a.decision,
      "evidence-used": a.evidenceUsed,
      "user-ack": a.userAck,
    };
    Object.keys(map).forEach(function (field) {
      if (map[field] == null) return;
      var node = card.querySelector('[data-field="' + field + '"]');
      if (node) node.textContent = String(map[field]);
    });
    if (a.ackLockedAt) {
      var t = card.querySelector('[data-field="ack-locked-at"]');
      if (t) { t.textContent = String(a.ackLockedAt); t.setAttribute("datetime", String(a.ackLockedAt)); }
      card.setAttribute("data-ack-value", String(a.ackLockedAt));
    }
  }

  function renderImplementationAgentDetail() {
    var host = document.querySelector('[data-list="changes-agent-detail"]');
    if (!host) return;
    var pkg = currentPackage();
    var changes = pkg && pkg.implementation && Array.isArray(pkg.implementation.changes) ? pkg.implementation.changes : [];
    if (!changes.length) return;
    host.innerHTML = changes.map(function (c, i) {
      var id = c && c.id ? String(c.id) : "change-" + (i + 1);
      var anchors = Array.isArray(c && c.codeAnchors) ? c.codeAnchors : [];
      return [
        "<li>",
        '<strong data-field="change-id">' + htmlEscape(id) + "</strong>",
        '<div class="kv-grid">',
        '<div class="k">Code anchors</div><div>' + (anchors.length ? anchors.map(function (a) { return "<code>" + htmlEscape(a) + "</code>"; }).join(" &middot; ") : "<em>none</em>") + "</div>",
        '<div class="k">Expected sign</div><div>' + htmlEscape(c && c.expectedSign || "unmeasured") + "</div>",
        '<div class="k">Magnitude band</div><div>' + htmlEscape(c && c.magnitudeBand || "unmeasured") + "</div>",
        '<div class="k">Validating exps</div><div>' + htmlEscape(c && c.validatingExp || "unmeasured") + "</div>",
        "</div>",
        "</li>",
      ].join("");
    }).join("");
  }

  function renderDirectoryAtlas() {
    var host = document.querySelector('[data-list="directory-atlas"]');
    if (!host) return;
    var pkg = currentPackage();
    var dirs = pkg && pkg.tracker && Array.isArray(pkg.tracker.experimentDirectories) ? pkg.tracker.experimentDirectories : [];
    if (!dirs.length) return;
    var byPhase = {};
    dirs.forEach(function (d) {
      var p = d && d.phase ? String(d.phase) : "unphased";
      if (!byPhase[p]) byPhase[p] = [];
      byPhase[p].push(d);
    });
    var html = "";
    Object.keys(byPhase).forEach(function (phase) {
      html += '<section class="phase-group" data-phase="' + htmlEscape(phase) + '">';
      html += "<h3>" + htmlEscape(phase) + "</h3>";
      byPhase[phase].forEach(function (d) {
        var paths = (d && d.paths) || {};
        var state = d && d.state ? String(d.state) : "QUEUED";
        html += '<div class="exp-block" data-exp-id="' + htmlEscape(d.expId || "unmeasured") + '" data-state="' + htmlEscape(state) + '">';
        html += '<header class="exp-block-header"><code>' + htmlEscape(d.expId || "unmeasured") + '</code><span class="chip exp-state-chip">' + htmlEscape(state) + "</span></header>";
        html += '<dl class="path-lines">';
        ["runtimeRoot", "logs", "outputs", "ckpts", "launcher"].forEach(function (k) {
          var label = k === "runtimeRoot" ? "runtime root" : k;
          html += "<dt>" + label + "</dt><dd><code>" + htmlEscape(paths[k] || "unmeasured") + "</code></dd>";
        });
        html += "</dl></div>";
      });
      html += "</section>";
    });
    host.innerHTML = html;
  }

  function renderChosenRoutePanel() {
    var card = document.querySelector('[data-card="chosen-route"]');
    if (!card) return;
    var pkg = currentPackage();
    var cr = pkg && pkg.chosenRoute;
    if (!cr) return;
    var map = {
      "chosen-route": cr.route,
      "chosen-route-reason": cr.reason,
      "user-ack": cr.userAck,
    };
    Object.keys(map).forEach(function (field) {
      if (map[field] == null) return;
      var node = card.querySelector('[data-field="' + field + '"]');
      if (node) node.textContent = String(map[field]);
    });
    if (cr.evidencePath) {
      var ep = card.querySelector('[data-artifact="chosen-route-evidence"]');
      if (ep) ep.textContent = String(cr.evidencePath);
    }
    // Resume Block headline cell sync.
    var rbCell = document.querySelector('[data-card="resume-block"] [data-field="next-action"]');
    if (rbCell && cr.route) {
      rbCell.innerHTML = "<b>Chosen route:</b> <code>" + htmlEscape(cr.route) + "</code> &mdash; " +
                        htmlEscape(cr.reason || "unmeasured") +
                        '. Full panel <a href="#chosen-route">below</a>.';
    }
    // Considered routes table.
    var considered = Array.isArray(pkg.consideredRoutes) ? pkg.consideredRoutes : [];
    if (considered.length) {
      var tbody = document.querySelector('[data-table-body="considered-routes"]');
      if (tbody) {
        tbody.innerHTML = considered.map(function (r) {
          return "<tr>" +
                 '<td data-route="' + htmlEscape(r.route || "") + '"><code>' + htmlEscape(r.route || "unmeasured") + "</code></td>" +
                 "<td>" + htmlEscape(r.considered || "unmeasured") + "</td>" +
                 "<td>" + htmlEscape(r.reason || "unmeasured") + "</td>" +
                 '<td><code>' + htmlEscape(r.evidencePath || "unmeasured") + "</code></td>" +
                 "</tr>";
        }).join("");
      }
    }
  }

  function renderResultBlocks() {
    var host = document.querySelector('[data-list="result-blocks"]');
    if (!host) return;
    var pkg = currentPackage();
    var blocks = pkg && Array.isArray(pkg.resultBlocks) ? pkg.resultBlocks : [];
    if (!blocks.length) return;
    host.innerHTML = blocks.map(function (b) {
      var phaseId = b && b.phaseId ? String(b.phaseId) : "unmeasured";
      var title = b && b.title ? String(b.title) : (phaseId + " — result");
      var summary = b && b.summary ? String(b.summary) : "unmeasured";
      var detail = b && b.detail ? String(b.detail) : "";
      var main = b && b.mainTable;
      var insights = Array.isArray(b && b.insights) ? b.insights : [];
      var ablations = Array.isArray(b && b.ablations) ? b.ablations : [];
      var mainHtml = "";
      if (main && Array.isArray(main.rows)) {
        var headers = Array.isArray(main.columns) ? main.columns : Object.keys(main.rows[0] || {});
        mainHtml = '<table class="data-table block-main-table"><thead><tr>' +
                   headers.map(function (h) { return "<th>" + htmlEscape(h) + "</th>"; }).join("") +
                   "</tr></thead><tbody>" +
                   main.rows.map(function (row) {
                     return "<tr>" + headers.map(function (h) {
                       var v = row[h];
                       return '<td' + (typeof v === "number" ? ' class="num"' : "") + ">" + htmlEscape(v == null ? "—" : v) + "</td>";
                     }).join("") + "</tr>";
                   }).join("") +
                   "</tbody></table>";
      }
      return [
        '<article class="result-block" data-result-block data-phase-id="' + htmlEscape(phaseId) + '">',
        "<h2>" + htmlEscape(title) + "</h2>",
        '<p class="block-summary">' + htmlEscape(summary) + "</p>",
        detail ? '<details class="block-detail"><summary>Full methodology &amp; provenance</summary><p class="card-text">' + htmlEscape(detail) + "</p></details>" : "",
        mainHtml,
        '<section class="block-insight"><h4>Insight</h4><ul class="block-insight-bullets">' +
          (insights.length ? insights.map(function (s) { return "<li>" + htmlEscape(s) + "</li>"; }).join("") :
                             '<li><em>No cells measured yet.</em></li>') +
          "</ul></section>",
        ablations.length ? '<details class="block-ablation"><summary>Ablations / peer tables</summary><ul>' +
          ablations.map(function (a) { return "<li>" + htmlEscape(a.title || "ablation") + "</li>"; }).join("") +
          "</ul></details>" : "",
        "</article>",
      ].join("");
    }).join("");
  }

  function renderInsightSubblocks() {
    var host = document.querySelector('[data-block="insight-body"]');
    if (!host) return;
    var pkg = currentPackage();
    var insights = pkg && Array.isArray(pkg.analysisInsights) ? pkg.analysisInsights : [];
    if (!insights.length) return;
    host.innerHTML = insights.map(function (s) {
      var id = s && s.id ? String(s.id) : "insight";
      var title = s && s.title ? String(s.title) : "Insight";
      var lead = s && s.lead ? String(s.lead) : "";
      var reading = s && s.reading ? String(s.reading) : "";
      var mechanism = s && s.mechanism ? String(s.mechanism) : "";
      var prov = s && s.provenance ? String(s.provenance) : "";
      return [
        '<details class="insight-subblock" id="insight-' + htmlEscape(id) + '">',
        "<summary>" + htmlEscape(title) + "</summary>",
        '<div class="insight-subblock-body">',
        lead ? '<p class="card-text">' + htmlEscape(lead) + "</p>" : "",
        reading ? '<p class="insight-reading">' + htmlEscape(reading) + "</p>" : "",
        mechanism ? "<h4>Mechanism</h4><p class=\"card-text\">" + htmlEscape(mechanism) + "</p>" : "",
        prov ? '<p class="insight-provenance">' + htmlEscape(prov) + "</p>" : "",
        "</div></details>",
      ].join("");
    }).join("");
  }

  function renderDocsIndex() {
    var host = document.querySelector('[data-list="docs-groups"]');
    if (!host) return;
    var pkg = currentPackage();
    var groups = pkg && Array.isArray(pkg.docsGroups) ? pkg.docsGroups : [];
    if (!groups.length) return;
    // Update lead.
    var ids = groups.map(function (g) { return g.id; }).filter(Boolean);
    var leadCount = document.querySelector('[data-field="docs-group-count"]');
    if (leadCount) leadCount.textContent = String(groups.length);
    var leadIds = document.querySelector('[data-field="docs-group-ids"]');
    if (leadIds) leadIds.textContent = ids.join(", ");
    host.innerHTML = groups.map(function (g) {
      var docs = Array.isArray(g && g.docs) ? g.docs : [];
      return [
        '<section class="docs-group" data-doc-group="' + htmlEscape(g.id || "") +
          '" data-doc-group-kind="' + htmlEscape(g.kind || "") +
          '" data-doc-group-rationale="' + htmlEscape(g.rationale || "") + '">',
        '<header class="docs-group-header"><h2>' + htmlEscape(g.title || g.id || "group") + "</h2>" +
          (g.lead ? '<p class="card-text">' + htmlEscape(g.lead) + "</p>" : "") + "</header>",
        '<div class="docs-grid">',
        docs.map(function (d) {
          var topics = Array.isArray(d.topics) ? d.topics : [];
          var related = Array.isArray(d.relatedPages) ? d.relatedPages : [];
          var citedBy = Array.isArray(d.citedByTasks) ? d.citedByTasks : [];
          return [
            '<article class="module-card doc-card"',
            ' data-doc-id="' + htmlEscape(d.id || "") + '"',
            ' data-doc-group="' + htmlEscape(g.id || "") + '"',
            ' data-doc-topics="' + htmlEscape(topics.join(" ")) + '"',
            ' data-doc-related-pages="' + htmlEscape(related.join(" ")) + '"',
            ' data-doc-cited-by-tasks="' + htmlEscape(citedBy.join(" ")) + '">',
            '<header class="doc-card-header">',
            "<h3>" + htmlEscape(d.title || d.id || "doc") + "</h3>",
            '<time class="doc-updated" datetime="' + htmlEscape(d.lastUpdated || "") + '">' + htmlEscape(d.lastUpdated || "") + "</time>",
            "</header>",
            '<p class="doc-tldr">' + htmlEscape(d.tldr || "unmeasured") + "</p>",
            '<div class="doc-tags">' + topics.map(function (t) { return '<span class="chip doc-tag">' + htmlEscape(t) + "</span>"; }).join("") + "</div>",
            '<details class="doc-preview">',
            '<summary>Preview &mdash; <a class="doc-open" href="' + htmlEscape(d.href || (d.id + ".html")) + '">open full &rarr;</a></summary>',
            d.preview ? '<p class="doc-preview-body">' + htmlEscape(d.preview) + "</p>" : "",
            related.length ? '<p class="doc-related"><strong>Related pages:</strong> ' + related.map(function (r) { return '<a href="../' + htmlEscape(r) + '"><code>' + htmlEscape(r) + "</code></a>"; }).join(" &middot; ") + "</p>" : "",
            citedBy.length ? '<p class="doc-cited-by"><strong>Cited by tasks:</strong> ' + citedBy.map(function (c) { return "<code>" + htmlEscape(c) + "</code>"; }).join(" &middot; ") + "</p>" : "",
            "</details>",
            "</article>",
          ].join("");
        }).join(""),
        "</div></section>",
      ].join("");
    }).join("");
  }

  function renderAll() {
    renderDashboardSummary();
    renderGlobalContext();
    renderRulesRegistry();
    renderProjectProfile();
    renderScopeProjection();
    renderCategoryPage();
    renderBrainstorms();
    renderPackageDetail();
    renderModulePage();
    renderStatusStrip();
    renderPackageNav();
    renderResumeBlock();
    renderPlanStatus();
    renderValidityCounts();
    renderHypothesisCheck();
    renderDashboardPackages();
    renderLearningsView();
    // Per-page canon painters (HTML design spec 2026-05-24).
    renderUserZoneIdentity();
    renderHeadline();
    renderKeyInsight();
    renderObjectiveContract();
    renderPipelineTimeline();
    renderImplementationPhaseStrip();
    renderImplementationChanges();
    renderImplementationAdjudication();
    renderImplementationAgentDetail();
    renderDirectoryAtlas();
    renderChosenRoutePanel();
    renderResultBlocks();
    renderInsightSubblocks();
    renderDocsIndex();
    setupCopyButtons();
    enhanceSortableTables();
  }

  window.__researchRenderers = window.__researchRenderers || [];
  window.__researchRenderers.push(renderAll);
  document.addEventListener("DOMContentLoaded", renderAll);
})();
