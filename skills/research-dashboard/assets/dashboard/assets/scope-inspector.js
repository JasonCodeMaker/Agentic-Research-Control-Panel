"use strict";

/* scope-inspector.js - live, read-only view of the Scope SSOT.
 *
 * Folds the canonical transition + triage logs in the browser. It encodes NO
 * SSOT schema rule: the tree comes from `parents` edges (not a level list) and
 * node detail is rendered from whatever `spec` fields a node carries, so a
 * new level or a new spec field shows up without changing this file. The
 * one shared convention is the writer's "active" status value (lib/scope_ssot).
 */
(function (root, factory) {
  var api = factory(root || {});
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  if (root) { root.ScopeInspector = api; }
  if (typeof document !== "undefined") { api._initWhenReady(); }
})(typeof self !== "undefined" ? self : (typeof globalThis !== "undefined" ? globalThis : this), function (root) {

  // ───────── pure logic (also unit-tested under node) ─────────

  var ACTIVE = "ACTIVE";          // a node is live while its status reads this (NODE_STATUS, shared with the writer lib/scope_ssot)
  var PENDING = "pending";        // a triage proposal awaits human disposition while its triage-record status reads this (triage log keeps lowercase; distinct from the ACTIVE node status and from the UI "active" tab name)

  function shortError(e) {
    var m = (e && e.message) ? e.message : String(e);
    return m.length > 120 ? m.slice(0, 117) + "..." : m;
  }

  function parseJsonl(text) {
    var records = [];
    var errors = [];
    var lines = String(text == null ? "" : text).split(/\r?\n/);
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (!line) { continue; }
      try {
        records.push(JSON.parse(line));
      } catch (e) {
        errors.push({ line: i + 1, message: shortError(e) });
      }
    }
    return { records: records, errors: errors };
  }

  // Replay the append-only log: the last transition per node_id wins.
  function foldTransitions(records) {
    var projection = {};
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r && r.node_id != null && r.node) { projection[r.node_id] = r.node; }
    }
    return projection;
  }

  // The latest transition record per node_id (its provenance / cause / op).
  function latestRecords(records) {
    var latest = {};
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r && r.node_id != null) { latest[r.node_id] = r; }
    }
    return latest;
  }

  // Every transition for each node_id, in file order.
  function historyByNode(records) {
    var groups = {};
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (!r || r.node_id == null) { continue; }
      if (!groups[r.node_id]) { groups[r.node_id] = []; }
      groups[r.node_id].push(r);
    }
    return groups;
  }

  function isActive(node) {
    return !!node && node.status === ACTIVE;
  }

  function byKey(a, b) { return a < b ? -1 : (a > b ? 1 : 0); }

  // Build a parent->children forest over the active nodes using only `parents`
  // edges. Roots are active nodes with no active parent; depth comes from the
  // graph, so no level name is named here.
  function activeTree(projection) {
    var active = {};
    Object.keys(projection).forEach(function (id) {
      if (isActive(projection[id])) { active[id] = projection[id]; }
    });
    var childrenOf = {};
    var hasActiveParent = {};
    Object.keys(active).forEach(function (id) {
      (active[id].parents || []).forEach(function (pid) {
        if (active[pid]) {
          if (!childrenOf[pid]) { childrenOf[pid] = []; }
          childrenOf[pid].push(id);
          hasActiveParent[id] = true;
        }
      });
    });
    var roots = Object.keys(active).filter(function (id) { return !hasActiveParent[id]; });
    roots.sort(byKey);
    Object.keys(childrenOf).forEach(function (pid) { childrenOf[pid].sort(byKey); });
    return { active: active, roots: roots, childrenOf: childrenOf };
  }

  function mergeRecord(base, update) {
    var out = {};
    Object.keys(base || {}).forEach(function (k) { out[k] = base[k]; });
    Object.keys(update || {}).forEach(function (k) {
      if (update[k] !== undefined) { out[k] = update[k]; }
    });
    return out;
  }

  // Latest status per triage id wins, while earlier proposal detail is retained.
  function foldTriage(records) {
    var latest = {};
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r && r.id != null) { latest[r.id] = mergeRecord(latest[r.id], r); }
    }
    var pending = [];
    var accepted = [];
    var rejected = [];
    var other = [];
    Object.keys(latest).forEach(function (id) {
      var item = latest[id];
      var status = String(item.status || "").toLowerCase();
      if (status === PENDING) { pending.push(item); }
      else if (status === "accepted") { accepted.push(item); }
      else if (status === "rejected") { rejected.push(item); }
      else { other.push(item); }
    });
    pending.sort(function (a, b) { return byKey(a.id, b.id); });
    accepted.sort(function (a, b) { return byKey(a.id, b.id); });
    rejected.sort(function (a, b) { return byKey(a.id, b.id); });
    other.sort(function (a, b) { return byKey(a.id, b.id); });
    return { pending: pending, accepted: accepted, rejected: rejected, other: other, disposed: accepted.concat(rejected, other) };
  }

  var WORD_RE = /[A-Za-z0-9]+(?:[@._:/+-][A-Za-z0-9]+)*|[\u4e00-\u9fff]/g;

  function wordCount(value) {
    return String(value == null ? "" : value).match(WORD_RE || []) || [];
  }

  function countWords(value) {
    return wordCount(value).length;
  }

  function schemaLevels(schema) {
    return (schema && schema.levels) || {};
  }

  function schemaForNode(node, schema) {
    return schemaLevels(schema)[node && node.level] || null;
  }

  function schemaField(schemaLevel, key) {
    return schemaLevel && schemaLevel.fields ? schemaLevel.fields[key] : null;
  }

  function issue(out, nodeId, severity, message) {
    out.push({ node_id: nodeId, severity: severity || "error", message: message });
  }

  function checkWordBounds(out, nodeId, field, value, min, max) {
    var n = countWords(value);
    if (typeof min === "number" && typeof max === "number" && (n < min || n > max)) {
      issue(out, nodeId, "error", field + " must be " + min + "-" + max + " words, got " + n);
    }
  }

  function validateFieldValue(out, nodeId, field, value, def) {
    if (!def) { return; }
    if (def.kind === "list") {
      if (!Array.isArray(value) || !value.length) {
        issue(out, nodeId, "error", field + " must be a non-empty list");
        return;
      }
      value.forEach(function (item, idx) {
        if (typeof item !== "string") {
          issue(out, nodeId, "error", field + "[" + idx + "] must be a string");
        } else {
          checkWordBounds(out, nodeId, field + "[" + idx + "]", item, def.minWords, def.maxWords);
        }
      });
      return;
    }
    if (def.kind === "ref") {
      if (typeof value !== "string" || !value.trim()) {
        issue(out, nodeId, "error", field + " must be a non-empty reference string");
      }
      return;
    }
    if (def.kind === "enum") {
      if ((def.values || []).indexOf(value) < 0) {
        issue(out, nodeId, "error", field + " must be one of " + (def.values || []).join(", "));
      }
      return;
    }
    if (def.kind === "metric" && value && typeof value === "object" && !Array.isArray(value)) {
      if (!Object.keys(value).length) { issue(out, nodeId, "error", field + " must be non-empty"); }
      return;
    }
    if (typeof value !== "string") {
      issue(out, nodeId, "error", field + " must be a string");
      return;
    }
    checkWordBounds(out, nodeId, field, value, def.minWords, def.maxWords);
  }

  function schemaHealth(projection, schema) {
    var issues = [];
    var oldNodeFields = (schema && schema.oldNodeFields) || [];
    var readingFields = (schema && schema.readingFields) || [];
    Object.keys(projection || {}).sort(byKey).forEach(function (id) {
      var node = projection[id] || {};
      var schemaLevel = schemaForNode(node, schema);
      oldNodeFields.forEach(function (key) {
        if (Object.prototype.hasOwnProperty.call(node, key)) {
          issue(issues, id, "error", "old field " + key + " is rejected");
        }
      });
      if (!node.source) { issue(issues, id, "warn", "source is missing"); }
      if (!schemaLevel) {
        issue(issues, id, "error", "unknown level " + (node.level || "-"));
        return;
      }
      var spec = node.spec;
      if (!spec || typeof spec !== "object" || Array.isArray(spec)) {
        issue(issues, id, "error", "spec must be an object");
        return;
      }
      var fields = schemaLevel.fields || {};
      Object.keys(fields).forEach(function (field) {
        if (!Object.prototype.hasOwnProperty.call(spec, field)) {
          issue(issues, id, "error", "missing spec field " + field);
        }
      });
      Object.keys(spec).forEach(function (field) {
        if (readingFields.indexOf(field) >= 0) {
          issue(issues, id, "error", "reading field " + field + " cannot live in a spec");
          return;
        }
        if (!Object.prototype.hasOwnProperty.call(fields, field)) {
          issue(issues, id, "error", "unknown spec field " + field);
          return;
        }
        validateFieldValue(issues, id, field, spec[field], fields[field]);
      });
    });
    return { ok: issues.length === 0, issues: issues };
  }

  function packageList(explicit) {
    if (explicit) { return explicit; }
    return (root && root.RESEARCH_PACKAGES) || [];
  }

  function proposalParents(item) {
    var proposed = item && item.proposed_node && typeof item.proposed_node === "object" ? item.proposed_node : {};
    var parents = (item && item.parents) || proposed.parents || [];
    return Array.isArray(parents) ? parents : [];
  }

  function pendingChildrenOf(pending, parentId) {
    return (pending || []).filter(function (item) {
      return proposalParents(item).indexOf(parentId) >= 0;
    });
  }

  function packagesForOrigin(originId, explicitPackages) {
    return packageList(explicitPackages).filter(function (p) {
      return p && p.sourceDirection === originId;
    });
  }

  function packageReadiness(projection, triage, packages) {
    var tree = activeTree(projection || {});
    var pending = (triage && triage.pending) || [];
    if (!tree.roots.length) {
      return {
        state: "missing_project",
        items: [],
        nextSkill: "/research-onboard",
        nextAction: "Create and ratify a Project before package work.",
      };
    }

    var branches = [];
    tree.roots.forEach(function (rootId) {
      (tree.childrenOf[rootId] || []).forEach(function (id) { branches.push(id); });
    });
    branches.sort(byKey);

    if (!branches.length) {
      var pendingBranches = [];
      tree.roots.forEach(function (rootId) {
        pendingChildrenOf(pending, rootId).forEach(function (item) { pendingBranches.push(item); });
      });
      if (pendingBranches.length) {
        return {
          state: "pending_direction",
          pendingCount: pendingBranches.length,
          items: [],
          nextSkill: "/research-scope",
          nextAction: "Accept, revise, or reject the pending Direction before creating a package.",
        };
      }
      return {
        state: "missing_direction",
        items: [],
        nextSkill: "/research-brainstorm",
        nextAction: "Shape and ratify a Direction before creating a package.",
      };
    }

    var items = branches.map(function (id) {
      var childIds = (tree.childrenOf[id] || []).slice().sort(byKey);
      var pendingTasks = pendingChildrenOf(pending, id);
      var linked = packagesForOrigin(id, packages);
      if (linked.length) {
        return {
          directionId: id,
          state: "materialized",
          packageId: linked[0].id || linked[0].name || "",
          packageCount: linked.length,
          taskCount: childIds.length,
          nextSkill: "/research-run",
          nextAction: "/research-run " + (linked[0].id || linked[0].name || "<package-id>"),
        };
      }
      if (childIds.length) {
        return {
          directionId: id,
          state: "ready_to_materialize",
          taskCount: childIds.length,
          nextSkill: "/research-package",
          nextAction: "/research-package from-scope " + id,
        };
      }
      if (pendingTasks.length) {
        return {
          directionId: id,
          state: "pending_tasks",
          pendingTaskCount: pendingTasks.length,
          taskCount: 0,
          nextSkill: "/research-scope",
          nextAction: "Accept, revise, or reject the pending validation Tasks before creating a package.",
        };
      }
      return {
        directionId: id,
        state: "missing_tasks",
        taskCount: 0,
        nextSkill: "/research-scope",
        nextAction: "Propose and ratify validation Tasks before creating a package.",
      };
    });

    return { state: "directions", items: items, nextSkill: null, nextAction: null };
  }

  function linkedPackages(nodeId, explicitPackages) {
    return packageList(explicitPackages).filter(function (p) {
      var matchedExperiments = (p.experiments || []).filter(function (exp) {
        return exp && exp.sourceTask === nodeId;
      });
      var direct = p.sourceDirection === nodeId;
      var task = (p.sourceTasks || []).some(function (m) { return m && m.id === nodeId; });
      if (!direct && !task && !matchedExperiments.length) { return false; }
      p.matchedExperiments = matchedExperiments;
      return true;
    });
  }

  function packageProvenanceHealth(projection, explicitPackages) {
    var issues = [];
    packageList(explicitPackages).forEach(function (p) {
      var pkgId = p.id || p.name || "package";
      if (p.sourceDirection && !projection[p.sourceDirection]) {
        issue(issues, pkgId, "warn", "sourceDirection points to missing Scope node " + p.sourceDirection);
      }
      (p.sourceTasks || []).forEach(function (task) {
        if (task && task.id && !projection[task.id]) {
          issue(issues, pkgId, "warn", "sourceTasks points to missing Scope node " + task.id);
        }
      });
      (p.experiments || []).forEach(function (exp) {
        if (exp && exp.sourceTask && !projection[exp.sourceTask]) {
          issue(issues, pkgId, "warn", "experiments[].sourceTask " + (exp.id || "-") +
            " points to missing Scope node " + exp.sourceTask);
        }
      });
    });
    return { ok: issues.length === 0, issues: issues };
  }

  function labelForField(schemaLevel, key) {
    var def = schemaField(schemaLevel, key);
    return (def && def.label) || humanizeKey(key);
  }

  function orderedSpecKeys(node, schema) {
    var spec = (node && node.spec) || {};
    var schemaLevel = schemaForNode(node, schema);
    var order = (schemaLevel && schemaLevel.order) || [];
    var seen = {};
    var keys = [];
    order.forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(spec, key)) {
        keys.push(key);
        seen[key] = true;
      }
    });
    Object.keys(spec).sort(byKey).forEach(function (key) {
      if (!seen[key]) { keys.push(key); }
    });
    return keys;
  }

  function valueSummary(value) {
    if (value == null || value === "") { return ""; }
    if (Array.isArray(value)) { return value.map(valueSummary).filter(Boolean).join("; "); }
    if (typeof value === "object") {
      if (value.name) { return String(value.name); }
      return JSON.stringify(value);
    }
    return String(value);
  }

  function summarizeNode(node, schema) {
    var schemaLevel = schemaForNode(node, schema);
    var spec = (node && node.spec) || {};
    var primary = (schemaLevel && schemaLevel.primary) || orderedSpecKeys(node, schema).slice(0, 1);
    var parts = [];
    primary.forEach(function (field) {
      if (Object.prototype.hasOwnProperty.call(spec, field)) {
        var text = valueSummary(spec[field]);
        if (text) { parts.push({ field: field, label: labelForField(schemaLevel, field), value: text }); }
      }
    });
    return {
      id: node && node.id,
      level: node && node.level,
      title: parts.length ? parts[0].value : ((node && node.id) || "Scope node"),
      parts: parts,
    };
  }

  function currentUnderstanding(projection, triage, packages, schema) {
    var tree = activeTree(projection || {});
    var activeIds = Object.keys(tree.active);
    var activeByLevel = {};
    activeIds.forEach(function (id) {
      var level = tree.active[id].level || "node";
      activeByLevel[level] = (activeByLevel[level] || 0) + 1;
    });
    var linked = {};
    activeIds.forEach(function (id) {
      linkedPackages(id, packages).forEach(function (p) { linked[p.id || p.name] = true; });
    });
    return {
      activeTotal: activeIds.length,
      activeByLevel: activeByLevel,
      pendingProposals: (triage && triage.pending ? triage.pending.length : 0),
      acceptedProposals: (triage && triage.accepted ? triage.accepted.length : 0),
      linkedPackages: Object.keys(linked).filter(Boolean).length,
      rootSummaries: tree.roots.map(function (id) { return summarizeNode(tree.active[id], schema); }),
    };
  }

  function flattenFields(prefix, value, out) {
    out = out || {};
    if (value == null || typeof value !== "object" || Array.isArray(value)) {
      out[prefix] = JSON.stringify(value);
      return out;
    }
    Object.keys(value).sort(byKey).forEach(function (key) {
      flattenFields(prefix ? prefix + "." + key : key, value[key], out);
    });
    return out;
  }

  function diffNodes(before, after) {
    var left = flattenFields("", before || {}, {});
    var right = flattenFields("", after || {}, {});
    var keys = {};
    Object.keys(left).forEach(function (k) { keys[k] = true; });
    Object.keys(right).forEach(function (k) { keys[k] = true; });
    return Object.keys(keys).sort(byKey).filter(function (k) {
      return left[k] !== right[k];
    }).map(function (k) {
      return {
        field: k,
        type: left[k] === undefined ? "added" : (right[k] === undefined ? "removed" : "changed"),
        before: left[k],
        after: right[k],
      };
    });
  }

  function historyTimeline(records) {
    var prev = {};
    var rows = [];
    (records || []).forEach(function (r, idx) {
      var nodeId = r && r.node_id;
      var before = nodeId && prev[nodeId] ? prev[nodeId].node : null;
      var row = mergeRecord(r || {}, { index: idx, diff: diffNodes(before, r && r.node) });
      rows.push(row);
      if (nodeId) { prev[nodeId] = r; }
    });
    return rows.reverse();
  }

  function buildSnapshot(transitions, triageRes, schema) {
    var parsed = parseJsonl(transitions.text);
    var triageParsed = parseJsonl(triageRes.text);
    var projection = foldTransitions(parsed.records);
    var triage = foldTriage(triageParsed.records);
    return {
      tStatus: transitions.status,
      triageStatus: triageRes.status,
      records: parsed.records,
      errors: parsed.errors,
      triageRecords: triageParsed.records,
      triageErrors: triageParsed.errors,
      projection: projection,
      latest: latestRecords(parsed.records),
      triage: triage,
      schema: schema || {},
      schemaHealth: schemaHealth(projection, schema || {}),
    };
  }

  var logic = {
    ACTIVE: ACTIVE,
    parseJsonl: parseJsonl,
    foldTransitions: foldTransitions,
    latestRecords: latestRecords,
    historyByNode: historyByNode,
    isActive: isActive,
    activeTree: activeTree,
    foldTriage: foldTriage,
    buildSnapshot: buildSnapshot,
    schemaHealth: schemaHealth,
    currentUnderstanding: currentUnderstanding,
    packageReadiness: packageReadiness,
    linkedPackages: linkedPackages,
    packageProvenanceHealth: packageProvenanceHealth,
    historyTimeline: historyTimeline,
  };

  // ───────── DOM controller (browser only) ─────────

  function initWhenReady() {
    if (typeof document === "undefined") { return; }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }

  var POLL_MS = 1500;

  // Mutable view state. Selection + active tab survive re-renders so a live
  // update under the cursor does not yank the drawer the user is reading.
  var state = {
    tab: "active",              // UI tab id (active|triage|history|raw) — lowercase carve-out; unrelated to the ACTIVE node status
    selection: null,            // { kind: "node"|"transaction"|"triage", id: "..." }
    transitionsPath: "../outputs/_scope/transitions.jsonl",
    triagePath: "../outputs/_scope/triage.jsonl",
    prevSig: null,
    data: null,                 // last good { tStatus, records, errors, projection, latest, triage }
    lastRefresh: "-",
    schema: null,
  };

  function $(sel, ctx) { return (ctx || document).querySelector(sel); }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function humanizeKey(key) {
    var s = String(key).replace(/_/g, " ").trim();
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
  }

  function isScalar(v) {
    return v == null || typeof v === "string" || typeof v === "number" || typeof v === "boolean";
  }

  // Render any value generically: scalars as text, arrays as lists, objects as
  // key/value lines. No field name is special-cased.
  function renderValue(value) {
    if (value == null || value === "") {
      return '<span class="unmeasured">unmeasured</span>';
    }
    if (isScalar(value)) {
      return '<span class="scope-value">' + esc(value) + "</span>";
    }
    if (Array.isArray(value)) {
      if (!value.length) { return '<span class="unmeasured">none</span>'; }
      return '<ul class="scope-list">' + value.map(function (item) {
        return "<li>" + (isScalar(item) ? esc(item) : renderValue(item)) + "</li>";
      }).join("") + "</ul>";
    }
    var rows = Object.keys(value).map(function (k) {
      return '<div class="k">' + esc(humanizeKey(k)) + "</div><div>" + renderValue(value[k]) + "</div>";
    });
    return '<div class="kv-grid scope-subgrid">' + rows.join("") + "</div>";
  }

  function renderSpec(node) {
    var spec = (node && node.spec) || {};
    var schema = state.schema || {};
    var schemaLevel = schemaForNode(node, schema);
    var keys = orderedSpecKeys(node, schema);
    if (!keys.length) { return '<p class="unmeasured">No spec fields declared.</p>'; }
    return keys.map(function (k) {
      return '<div class="scope-field"><div class="k">' + esc(labelForField(schemaLevel, k)) + "</div>" +
        renderValue(spec[k]) + "</div>";
    }).join("");
  }

  function statusChip(status) {
    var s = status || "unknown";
    return '<span class="chip" data-status="' + esc(s) + '">' + esc(s) + "</span>";
  }

  function combinedSchemaHealth(data) {
    var base = (data && data.schemaHealth) || { ok: true, issues: [] };
    var pkg = packageProvenanceHealth((data && data.projection) || {}, packageList());
    var issues = (base.issues || []).concat(pkg.issues || []);
    return { ok: issues.length === 0, issues: issues };
  }

  function renderUnderstanding(data) {
    var host = $("[data-section='understanding']");
    if (!host) { return; }
    if (!data) {
      host.innerHTML = '<div class="empty-state">Loading current understanding...</div>';
      return;
    }
    var summary = currentUnderstanding(data.projection, data.triage, packageList(), data.schema);
    var levelRows = Object.keys(summary.activeByLevel).sort(byKey).map(function (level) {
      return '<div class="status-cell"><div class="k">' + esc(humanizeKey(level)) + '</div><div class="v">' +
        esc(summary.activeByLevel[level]) + "</div></div>";
    }).join("");
    var roots = summary.rootSummaries.length
      ? summary.rootSummaries.map(function (item) {
          return '<li><code>' + esc(item.id || "-") + "</code> " + esc(item.title || "-") + "</li>";
        }).join("")
      : '<li>No active root node.</li>';
    host.innerHTML = [
      '<article class="scope-understanding-card">',
      '<div class="scope-section-head"><div><div class="k">Current understanding</div>',
      '<h2>What the agent currently treats as scope</h2></div></div>',
      '<div class="status-strip scope-summary-strip">',
      '<div class="status-cell"><div class="k">Active nodes</div><div class="v">' + esc(summary.activeTotal) + "</div></div>",
      levelRows,
      '<div class="status-cell"' + (summary.pendingProposals ? ' data-state="warn"' : "") + '><div class="k">Pending proposals</div><div class="v">' + esc(summary.pendingProposals) + "</div></div>",
      '<div class="status-cell"' + (summary.acceptedProposals ? ' data-state="warn"' : "") + '><div class="k">Accepted proposals</div><div class="v">' + esc(summary.acceptedProposals) + "</div></div>",
      '<div class="status-cell"><div class="k">Linked packages</div><div class="v">' + esc(summary.linkedPackages) + "</div></div>",
      "</div>",
      '<ul class="scope-list scope-root-summary">' + roots + "</ul>",
      "</article>",
    ].join("");
  }

  function readinessTitle(stateValue) {
    var labels = {
      missing_project: "Project needed",
      missing_direction: "Direction needed",
      pending_direction: "Direction waiting",
      missing_tasks: "Validation Tasks needed",
      pending_tasks: "Validation Tasks waiting",
      ready_to_materialize: "Ready to materialize",
      materialized: "Package exists",
    };
    return labels[stateValue] || humanizeKey(stateValue);
  }

  function renderPackageReadiness(data) {
    var host = $("[data-section='package-readiness']");
    if (!host) { return; }
    if (!data) {
      host.innerHTML = '<div class="empty-state">Checking Package readiness...</div>';
      return;
    }
    var readiness = packageReadiness(data.projection, data.triage, packageList());
    var body = "";
    if (readiness.items && readiness.items.length) {
      body = '<div class="scope-forest">' + readiness.items.map(function (item) {
        var facts = [
          ["State", esc(readinessTitle(item.state))],
          ["Validation Tasks", esc(item.taskCount != null ? item.taskCount : 0)],
          ["Next skill", "<code>" + esc(item.nextSkill || "-") + "</code>"],
          ["Next action", "<code>" + esc(item.nextAction || "-") + "</code>"],
        ];
        if (item.pendingTaskCount) { facts.splice(2, 0, ["Pending Tasks", esc(item.pendingTaskCount)]); }
        if (item.packageId) { facts.splice(2, 0, ["Package", "<code>" + esc(item.packageId) + "</code>"]); }
        var rows = facts.map(function (r) {
          return '<div class="k">' + esc(r[0]) + "</div><div>" + r[1] + "</div>";
        }).join("");
        return [
          '<article class="scope-node scope-readiness-node">',
          '<div class="scope-node-head"><div><div class="k">Package readiness</div>',
          '<h3><code>' + esc(item.directionId || "-") + "</code></h3></div>",
          statusChip(readinessTitle(item.state)),
          "</div>",
          '<div class="kv-grid scope-dossier-grid">' + rows + "</div>",
          "</article>",
        ].join("");
      }).join("") + "</div>";
    } else {
      body = '<div class="status-strip scope-summary-strip">' +
        '<div class="status-cell"><div class="k">State</div><div class="v">' +
        esc(readinessTitle(readiness.state)) + "</div></div>" +
        '<div class="status-cell"><div class="k">Next skill</div><div class="v"><code>' +
        esc(readiness.nextSkill || "-") + "</code></div></div>" +
        '<div class="status-cell"><div class="k">Next action</div><div class="v"><code>' +
        esc(readiness.nextAction || "-") + "</code></div></div>" +
        "</div>";
    }
    host.innerHTML = [
      '<article class="scope-understanding-card">',
      '<div class="scope-section-head"><div><div class="k">Package readiness</div>',
      '<h2>Can committed Scope become a package?</h2></div></div>',
      body,
      "</article>",
    ].join("");
  }

  function renderSchemaHealth(data) {
    var host = $("[data-section='schema-health']");
    if (!host) { return; }
    if (!data) {
      host.innerHTML = '<div class="empty-state">Checking schema...</div>';
      return;
    }
    var health = combinedSchemaHealth(data);
    var issues = health.issues || [];
    var issueHtml = issues.length
      ? '<ul class="scope-list">' + issues.slice(0, 12).map(function (item) {
          return '<li><span class="chip" data-status="' + esc(item.severity || "error") + '">' +
            esc(item.severity || "error") + '</span> <code>' + esc(item.node_id || "-") + "</code> " +
            esc(item.message || "") + "</li>";
        }).join("") + "</ul>"
      : '<p class="scope-value">All folded Scope nodes match the browser schema snapshot.</p>';
    if (issues.length > 12) {
      issueHtml += '<p class="scope-note">' + esc(issues.length - 12) + " more issues hidden; open Raw Log for the full source.</p>";
    }
    host.innerHTML = [
      '<article class="scope-understanding-card" data-schema-ok="' + (health.ok ? "true" : "false") + '">',
      '<div class="scope-section-head"><div><div class="k">Schema health</div>',
      '<h2>' + (health.ok ? "Scope schema ok" : "Scope schema needs attention") + "</h2></div>",
      statusChip(health.ok ? "OK" : "CHECK"),
      "</div>",
      issueHtml,
      "</article>",
    ].join("");
  }

  // ── tree (Active Scope) ──

  function nodeCardHtml(id, tree, depth) {
    var node = tree.active[id];
    var children = tree.childrenOf[id] || [];
    var selected = state.selection && state.selection.kind === "node" && state.selection.id === id;
    var summary = summarizeNode(node, state.schema || {});
    var links = linkedPackages(id);
    var packageSummary = links.length
      ? links.length + " linked " + (links.length === 1 ? "package" : "packages")
      : "No linked package";
    var head = [
      '<div class="scope-node-head">',
      "<div>",
      '<div class="k">' + esc(node.level || "node") + "</div>",
      "<h3>" + esc(summary.title) + "</h3>",
      '<p class="scope-node-id"><code>' + esc(id) + "</code></p>",
      "</div>",
      statusChip(node.status),
      "</div>",
    ].join("");
    var body = renderSpec(node);
    var childHtml = children.length
      ? '<div class="scope-children">' + children.map(function (cid) {
          return nodeCardHtml(cid, tree, depth + 1);
        }).join("") + "</div>"
      : "";
    return [
      '<article class="scope-node" data-depth="' + depth + '"' +
        (selected ? ' data-selected="true"' : "") +
        ' data-select-node="' + esc(id) + '" tabindex="0" role="button">',
      head,
      '<div class="scope-impact-line">' + esc(packageSummary) + " &middot; " +
        children.length + " active " + (children.length === 1 ? "child" : "children") + "</div>",
      '<div class="scope-node-fields">' + body + "</div>",
      "</article>",
      childHtml,
    ].join("");
  }

  function renderActive(panel, data) {
    if (data.tStatus === "unreachable") {
      panel.innerHTML = cannotReadNotice();
      return;
    }
    if (data.tStatus === "missing") {
      panel.innerHTML = '<div class="empty-state">No committed Scope SSOT found yet.</div>';
      return;
    }
    if (data.tStatus === "empty" || !data.records.length) {
      panel.innerHTML = '<div class="empty-state">Scope log exists but has no committed nodes.</div>';
      return;
    }
    var tree = activeTree(data.projection);
    if (!tree.roots.length) {
      var n = data.triage.pending.length;
      var hint = n
        ? '<p>' + n + ' pending ' + (n === 1 ? "proposal" : "proposals") +
          ' await disposition. <a href="#" data-go-tab="triage">Open Pending Triage</a>.</p>'
        : "<p>No pending proposals in the Triage queue either.</p>";
      panel.innerHTML = '<div class="notice"><strong>No active Project node.</strong> ' +
        "Nothing is committed at the root of the objective cascade yet. " + hint + "</div>";
      return;
    }
    panel.innerHTML = '<div class="scope-forest">' +
      tree.roots.map(function (id) { return nodeCardHtml(id, tree, 0); }).join("") + "</div>";
  }

  // ── pending triage ──

  function proposalTargetId(item) {
    return item.node_id || item.target_node || (item.proposed_node && item.proposed_node.id) || "-";
  }

  function proposalDossierRows(item) {
    var target = proposalTargetId(item);
    return [
      ["Change", esc(item.change || item.title || "Scope change proposal")],
      ["Why", esc(item.rationale || item.cause || item.reason || "No rationale recorded.")],
      ["Target", "<code>" + esc(target) + "</code>"],
      ["Operation", esc(item.op || item.operation || "-")],
      ["Gate", esc(item.gate || "-")],
      ["Affected packages", packageLinkHtml(linkedPackages(target))],
      ["Next action", esc(String(item.status || "").toLowerCase() === "accepted"
        ? "Run scope-transition to commit or reject the accepted proposal."
        : "Review the proposed node before disposition.")],
    ];
  }

  function diffHtml(diff) {
    if (!diff || !diff.length) { return '<p class="unmeasured">No field-level diff available.</p>'; }
    return '<ul class="scope-list scope-diff-list">' + diff.slice(0, 10).map(function (d) {
      return '<li><span class="chip" data-status="' + esc(d.type) + '">' + esc(d.type) +
        '</span> <code>' + esc(d.field) + "</code></li>";
    }).join("") + "</ul>";
  }

  function proposalDiff(item) {
    var target = proposalTargetId(item);
    var current = state.data && state.data.projection ? state.data.projection[target] : null;
    return diffNodes(current, item.proposed_node || item.node || null);
  }

  function proposalHtml(item) {
    var selected = state.selection && state.selection.kind === "triage" && state.selection.id === item.id;
    var rows = proposalDossierRows(item).map(function (r) {
      return '<div class="k">' + esc(r[0]) + "</div><div>" + r[1] + "</div>";
    }).join("");
    return [
      '<article class="scope-node scope-proposal"' + (selected ? ' data-selected="true"' : "") +
        ' data-select-triage="' + esc(item.id) + '" tabindex="0" role="button">',
      '<div class="scope-node-head"><div><div class="k">Proposal</div><h3>' + esc(item.id) + "</h3></div>" +
        statusChip(item.status || PENDING) + "</div>",
      '<div class="kv-grid scope-dossier-grid">' + rows + "</div>",
      '<div class="scope-drawer-section"><div class="scope-drawer-label">Current vs proposed</div>' +
        diffHtml(proposalDiff(item)) + "</div>",
      "</article>",
    ].join("");
  }

  function renderTriage(panel, data) {
    var pending = data.triage.pending;
    var accepted = data.triage.accepted || [];
    var rejected = data.triage.rejected || [];
    var other = data.triage.other || [];
    var sections = [];
    if (data.triageStatus !== "ok" && data.triageStatus !== "empty" && data.triageStatus !== "missing") {
      sections.push('<div class="notice"><strong>Triage log is not readable.</strong> Pending decisions may be hidden.</div>');
    }
    if (data.triageErrors && data.triageErrors.length) {
      sections.push('<div class="notice"><strong>Triage parse errors</strong><ul class="scope-list">' +
        data.triageErrors.map(function (e) {
          return "<li>line " + e.line + ": " + esc(e.message) + "</li>";
        }).join("") + "</ul></div>");
    }
    if (!pending.length && !accepted.length && !rejected.length && !other.length) {
      panel.innerHTML = sections.join("") + '<div class="empty-state">No scope proposals recorded. The agent may propose ' +
        "changes here; only the user disposes them.</div>";
      return;
    }
    sections.push('<p class="scope-note">Proposal records are suggestions, not active Scope, until a gated transition commits them.</p>');
    if (pending.length) {
      sections.push('<section class="scope-triage-bucket"><h2>Pending</h2><div class="scope-forest">' +
        pending.map(proposalHtml).join("") + "</div></section>");
    }
    if (accepted.length) {
      sections.push('<section class="scope-triage-bucket"><h2>Accepted - needs scope-transition</h2><div class="scope-forest">' +
        accepted.map(proposalHtml).join("") + "</div></section>");
    }
    if (rejected.length) {
      sections.push('<section class="scope-triage-bucket"><h2>Rejected</h2><div class="scope-forest">' +
        rejected.map(proposalHtml).join("") + "</div></section>");
    }
    if (other.length) {
      sections.push('<section class="scope-triage-bucket"><h2>Other disposed</h2><div class="scope-forest">' +
        other.map(proposalHtml).join("") + "</div></section>");
    }
    panel.innerHTML = sections.join("");
  }

  // ── history ──

  function renderHistory(panel, data) {
    if (!data.records.length) {
      panel.innerHTML = '<div class="empty-state">No transitions recorded yet.</div>';
      return;
    }
    var rows = historyTimeline(data.records);
    panel.innerHTML = [
      '<section class="scope-history-group"><h2 class="scope-history-head">Recent changes</h2><div class="timeline">',
      rows.map(function (r) {
        var selected = state.selection && state.selection.kind === "transaction" && state.selection.id === r.transaction_id;
        var meta = [];
        if (r.cause) { meta.push("<p class='card-text'>" + esc(r.cause) + "</p>"); }
        if (r.trigger) { meta.push("<p class='card-text'><b>Trigger:</b> " + esc(r.trigger) + "</p>"); }
        return [
          '<div class="timeline-item">',
          '<div class="when">v' + esc(r.scope_version != null ? r.scope_version :
            (r.node && r.node.version != null ? r.node.version : "?")) + "</div>",
          '<div class="dot-col"><span class="dot"></span><span class="line"></span></div>',
          '<div class="timeline-body scope-history-row' + (selected ? " is-selected" : "") +
            '" data-select-txn="' + esc(r.transaction_id || "") + '" tabindex="0" role="button">',
          "<h3>" + esc(r.op || "transition") + "</h3>",
          '<p class="scope-history-txn"><code>' + esc(r.node_id || "-") + "</code></p>",
          '<p class="scope-history-txn"><code>' + esc(r.transaction_id || "-") + "</code></p>",
          meta.join(""),
          diffHtml(r.diff),
          "</div>",
          "</div>",
        ].join("");
      }).join(""),
      "</div></section>",
    ].join("");
  }

  // ── raw log ──

  function renderRaw(panel, data) {
    var parts = [];
    if (data.errors.length) {
      parts.push('<div class="notice"><strong>Transition parse errors</strong><ul class="scope-list">' +
        data.errors.map(function (e) {
          return "<li>line " + e.line + ": " + esc(e.message) + "</li>";
        }).join("") + "</ul></div>");
    }
    if (data.triageErrors.length) {
      parts.push('<div class="notice"><strong>Triage parse errors</strong><ul class="scope-list">' +
        data.triageErrors.map(function (e) {
          return "<li>line " + e.line + ": " + esc(e.message) + "</li>";
        }).join("") + "</ul></div>");
    }
    if (!data.records.length && !data.errors.length && !data.triageRecords.length && !data.triageErrors.length) {
      panel.innerHTML = '<div class="empty-state">No records to show.</div>';
      return;
    }
    var body = data.records.map(function (r) {
      return esc(JSON.stringify(r, null, 2));
    }).join("\n\n");
    var triageBody = data.triageRecords.map(function (r) {
      return esc(JSON.stringify(r, null, 2));
    }).join("\n\n");
    parts.push('<h2 class="scope-history-head">Transitions</h2><div class="code-box"><code>' + body + "</code></div>");
    parts.push('<h2 class="scope-history-head">Triage</h2><div class="code-box"><code>' + triageBody + "</code></div>");
    panel.innerHTML = parts.join("");
  }

  // ── detail drawer ──

  function pkgHref(p) {
    if (p.detailPath) { return p.detailPath; }
    return "packages/" + encodeURIComponent(p.id) + "/index.html";
  }

  function packageLinkHtml(links) {
    if (!links.length) { return '<span class="unmeasured">No package links found.</span>'; }
    return '<ul class="scope-list scope-package-list">' + links.map(function (p) {
      var exp = (p.matchedExperiments || []).map(function (e) {
        return e.id ? e.id + (e.status ? " (" + e.status + ")" : "") : "";
      }).filter(Boolean).join(", ");
      var meta = [];
      if (p.status) { meta.push("status " + p.status); }
      if (p.activeGate) { meta.push("gate " + p.activeGate); }
      if (p.nextRoute) { meta.push("next " + p.nextRoute); }
      if (exp) { meta.push("experiments " + exp); }
      return '<li><a href="' + esc(pkgHref(p)) + '">' + esc(p.name || p.id) + "</a>" +
        (meta.length ? '<span class="scope-package-meta"> - ' + esc(meta.join("; ")) + "</span>" : "") +
        "</li>";
    }).join("") + "</ul>";
  }

  function drawerForNode(id, data) {
    var node = data.projection[id];
    if (!node) { return '<p class="unmeasured">Node ' + esc(id) + " is not in the current projection.</p>"; }
    var rec = data.latest[id] || {};
    var rows = [
      ["Node id", "<code>" + esc(id) + "</code>"],
      ["Level", esc(node.level || "-")],
      ["Status", statusChip(node.status)],
      ["Version", esc(node.version != null ? node.version : "-")],
      ["Parents", (node.parents && node.parents.length) ? renderValue(node.parents) : '<span class="unmeasured">root</span>'],
      ["Source", node.source ? "<code>" + esc(node.source) + "</code>" : '<span class="unmeasured">-</span>'],
    ];
    var prov = [
      ["Latest txn", rec.transaction_id ? "<code>" + esc(rec.transaction_id) + "</code>" : '<span class="unmeasured">-</span>'],
      ["Op", esc(rec.op || "-")],
      ["Gate", esc(rec.gate || "-")],
      ["Trigger", rec.trigger ? esc(rec.trigger) : '<span class="unmeasured">-</span>'],
      ["Cause", rec.cause ? esc(rec.cause) : '<span class="unmeasured">-</span>'],
    ];
    ["invalidates", "reopens", "dial_revert"].forEach(function (k) {
      if (rec[k] && rec[k].length) { prov.push([humanizeKey(k), renderValue(rec[k])]); }
    });
    var links = linkedPackages(id);
    var linkHtml = packageLinkHtml(links);
    return [
      kvBlock(rows),
      '<div class="scope-drawer-section"><div class="scope-drawer-label">Spec</div>' +
        renderSpec(node) + "</div>",
      '<div class="scope-drawer-section"><div class="scope-drawer-label">Latest transition</div>' +
        kvBlock(prov) + "</div>",
      '<div class="scope-drawer-section"><div class="scope-drawer-label">Linked packages</div>' +
        linkHtml + "</div>",
    ].join("");
  }

  function drawerForTxn(txnId, data) {
    var rec = null;
    for (var i = 0; i < data.records.length; i++) {
      if (data.records[i].transaction_id === txnId) { rec = data.records[i]; break; }
    }
    if (!rec) { return '<p class="unmeasured">Transition ' + esc(txnId) + " not found.</p>"; }
    var before = null;
    for (var j = 0; j < data.records.length; j++) {
      if (data.records[j].transaction_id === txnId) { break; }
      if (data.records[j].node_id === rec.node_id) { before = data.records[j].node; }
    }
    var diff = diffNodes(before, rec.node);
    var links = linkedPackages(rec.node_id);
    var rows = [
      ["Txn id", "<code>" + esc(rec.transaction_id) + "</code>"],
      ["Node id", "<code>" + esc(rec.node_id) + "</code>"],
      ["Level", esc(rec.level || "-")],
      ["Op", esc(rec.op || "-")],
      ["Gate", esc(rec.gate || "-")],
      ["Scope version", esc(rec.scope_version != null ? rec.scope_version : "-")],
      ["Trigger", rec.trigger ? esc(rec.trigger) : '<span class="unmeasured">-</span>'],
      ["Cause", rec.cause ? esc(rec.cause) : '<span class="unmeasured">-</span>'],
    ];
    ["invalidates", "reopens", "dial_revert"].forEach(function (k) {
      if (rec[k] && rec[k].length) { rows.push([humanizeKey(k), renderValue(rec[k])]); }
    });
    return [
      kvBlock(rows),
      '<div class="scope-drawer-section"><div class="scope-drawer-label">Field diff</div>' +
        diffHtml(diff) + "</div>",
      rec.node
        ? '<div class="scope-drawer-section"><div class="scope-drawer-label">Node snapshot</div>' +
          renderSpec(rec.node) + "</div>"
        : "",
      '<div class="scope-drawer-section"><div class="scope-drawer-label">Affected packages</div>' +
        packageLinkHtml(links) + "</div>",
    ].join("");
  }

  function drawerForTriage(id, data) {
    var item = null;
    data.triage.pending.concat(data.triage.disposed).forEach(function (p) {
      if (p.id === id) { item = p; }
    });
    if (!item) { return '<p class="unmeasured">Proposal ' + esc(id) + " not found.</p>"; }
    var rows = proposalDossierRows(item);
    var raw = Object.keys(item).map(function (k) { return [humanizeKey(k), renderValue(item[k])]; });
    return '<p class="scope-note">A proposal is a suggestion, never active scope.</p>' +
      kvBlock(rows) +
      '<div class="scope-drawer-section"><div class="scope-drawer-label">Current vs proposed</div>' +
        diffHtml(proposalDiff(item)) + "</div>" +
      '<div class="scope-drawer-section"><div class="scope-drawer-label">Raw proposal</div>' +
        kvBlock(raw) + "</div>";
  }

  function kvBlock(rows) {
    return '<div class="kv-grid scope-drawer-grid">' + rows.map(function (r) {
      return '<div class="k">' + esc(r[0]) + "</div><div>" + r[1] + "</div>";
    }).join("") + "</div>";
  }

  function renderDrawer() {
    var drawer = $("[data-section='drawer']");
    if (!drawer) { return; }
    var data = state.data;
    var sel = state.selection;
    if (!data || !sel) {
      drawer.innerHTML = '<div class="scope-drawer-empty">Select a node, transition, or proposal to inspect it.</div>';
      return;
    }
    var body = "";
    if (sel.kind === "node") { body = drawerForNode(sel.id, data); }
    else if (sel.kind === "transaction") { body = drawerForTxn(sel.id, data); }
    else if (sel.kind === "triage") { body = drawerForTriage(sel.id, data); }
    drawer.innerHTML = '<div class="scope-drawer-head">Detail</div>' + body;
  }

  // ── health strip + tabs ──

  function renderHealth(data) {
    var strip = $("[data-section='health']");
    if (!strip) { return; }
    var latestTxn = data.records.length ? (data.records[data.records.length - 1].transaction_id || "-") : "-";
    var latestVer = "-";
    data.records.forEach(function (r) {
      var v = r.scope_version != null ? r.scope_version : (r.node && r.node.version);
      if (typeof v === "number" && (latestVer === "-" || v > latestVer)) { latestVer = v; }
    });
    var srcState = data.tStatus === "ok" ? "ok" :
      (data.tStatus === "empty" ? "empty" : (data.tStatus === "missing" ? "missing" : "unreachable"));
    var triageState = data.triageStatus === "ok" ? "ok" :
      (data.triageStatus === "empty" ? "empty" : (data.triageStatus === "missing" ? "missing" : "unreachable"));
    var health = combinedSchemaHealth(data);
    var cells = [
      ["Scope source", "<span class='hint'>" + esc(state.transitionsPath) + "</span>", srcState],
      ["Triage source", "<span class='hint'>" + esc(state.triagePath) + "</span>", triageState],
      ["Latest version", "v" + esc(latestVer), null],
      ["Latest txn", "<span class='hint'>" + esc(latestTxn) + "</span>", null],
      ["Pending proposals", esc(data.triage.pending.length), data.triage.pending.length ? "warn" : null],
      ["Accepted proposals", esc((data.triage.accepted || []).length), (data.triage.accepted || []).length ? "warn" : null],
      ["Scope parse errors", esc(data.errors.length), data.errors.length ? "error" : null],
      ["Triage parse errors", esc(data.triageErrors.length), data.triageErrors.length ? "error" : null],
      ["Schema issues", esc((health.issues || []).length), health.ok ? null : "error"],
      ["Last refresh", "<span class='hint'>" + esc(state.lastRefresh) + "</span>", null],
    ];
    strip.innerHTML = cells.map(function (c) {
      return '<div class="status-cell"' + (c[2] ? ' data-state="' + c[2] + '"' : "") + '>' +
        '<div class="k">' + esc(c[0]) + '</div><div class="v">' + c[1] + "</div></div>";
    }).join("");
  }

  function cannotReadNotice() {
    return '<div class="notice"><strong>Cannot read ' + esc(state.transitionsPath) + ".</strong> " +
      "Serve from repo root with <code>python -m http.server</code> and open " +
      "<code>/research_html/scope.html</code>. Opening the file directly with a " +
      "<code>file://</code> URL blocks local fetches in most browsers.</div>";
  }

  function setTab(tab) {
    state.tab = tab;
    var tabs = document.querySelectorAll("[data-tab]");
    for (var i = 0; i < tabs.length; i++) {
      var t = tabs[i].getAttribute("data-tab");
      if (t === tab) { tabs[i].setAttribute("aria-current", "page"); }
      else { tabs[i].removeAttribute("aria-current"); }
    }
    var panels = document.querySelectorAll("[data-tabpanel]");
    for (var j = 0; j < panels.length; j++) {
      if (panels[j].getAttribute("data-tabpanel") === tab) { panels[j].removeAttribute("hidden"); }
      else { panels[j].setAttribute("hidden", "hidden"); }
    }
    renderTabs();
  }

  function renderTabs() {
    var data = state.data;
    if (!data) { return; }
    renderUnderstanding(data);
    renderPackageReadiness(data);
    renderSchemaHealth(data);
    var active = $("[data-tabpanel='active']");
    var triage = $("[data-tabpanel='triage']");
    var history = $("[data-tabpanel='history']");
    var raw = $("[data-tabpanel='raw']");
    if (active) { renderActive(active, data); }
    if (triage) { renderTriage(triage, data); }
    if (history) { renderHistory(history, data); }
    if (raw) { renderRaw(raw, data); }
    renderDrawer();
  }

  // ── fetch + poll ──

  function fetchText(path) {
    // Resolve to a status the UI can explain: ok / empty / missing / unreachable.
    return fetch(path, { cache: "no-store" }).then(function (resp) {
      if (resp.status === 404) { return { status: "missing", text: "" }; }
      if (!resp.ok) { return { status: "unreachable", text: "" }; }
      return resp.text().then(function (text) {
        return { status: text.trim() ? "ok" : "empty", text: text };
      });
    }).catch(function () {
      return { status: "unreachable", text: "" };
    });
  }

  function build(transitions, triageRes) {
    return buildSnapshot(transitions, triageRes, state.schema || {});
  }

  function refresh() {
    Promise.all([fetchText(state.transitionsPath), fetchText(state.triagePath)])
      .then(function (res) {
        var sig = res[0].status + "::" + res[0].text + "||" + res[1].text;
        state.lastRefresh = new Date().toLocaleTimeString();
        if (sig === state.prevSig && state.data) {
          renderHealth(state.data);   // keep the refresh clock fresh without re-rendering panels
          return;
        }
        state.prevSig = sig;
        state.data = build(res[0], res[1]);
        renderHealth(state.data);
        renderTabs();
      });
  }

  function onClick(e) {
    var go = e.target.closest("[data-go-tab]");
    if (go) { e.preventDefault(); setTab(go.getAttribute("data-go-tab")); return; }
    var tabEl = e.target.closest("[data-tab]");
    if (tabEl) { e.preventDefault(); setTab(tabEl.getAttribute("data-tab")); return; }
    var node = e.target.closest("[data-select-node]");
    if (node) { select("node", node.getAttribute("data-select-node")); return; }
    var txn = e.target.closest("[data-select-txn]");
    if (txn) { select("transaction", txn.getAttribute("data-select-txn")); return; }
    var prop = e.target.closest("[data-select-triage]");
    if (prop) { select("triage", prop.getAttribute("data-select-triage")); return; }
    if (e.target.closest("[data-action='refresh']")) { e.preventDefault(); refresh(); }
  }

  function onKey(e) {
    if (e.key !== "Enter" && e.key !== " ") { return; }
    var sel = e.target.closest("[data-select-node],[data-select-txn],[data-select-triage]");
    if (sel) { e.preventDefault(); onClick({ target: e.target, currentTarget: e.currentTarget }); }
  }

  function select(kind, id) {
    state.selection = { kind: kind, id: id };
    renderTabs();   // refresh data-selected markers + drawer
  }

  function init() {
    var body = document.body;
    state.transitionsPath = body.getAttribute("data-transitions") || state.transitionsPath;
    state.triagePath = body.getAttribute("data-triage") || state.triagePath;
    state.schema = root.SCOPE_SCHEMA || {};
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    setTab(state.tab);
    refresh();
    if (typeof window !== "undefined") {
      window.__researchRenderers = window.__researchRenderers || [];
      if (window.__researchRenderers.indexOf(refresh) === -1) {
        window.__researchRenderers.push(refresh);
      }
    }
    setInterval(refresh, POLL_MS);
  }

  logic._initWhenReady = initWhenReady;
  return logic;
});
