"use strict";

/* scope-inspector.js - live, read-only view of the Scope SSOT.
 *
 * Folds the canonical transition + triage logs in the browser. It encodes NO
 * SSOT schema rule: the tree comes from `parents` edges (not a level list) and
 * node detail is rendered from whatever `yardstick` fields a node carries, so a
 * new level or a new yardstick field shows up without changing this file. The
 * one shared convention is the writer's "active" status value (lib/scope_ssot).
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  if (root) { root.ScopeInspector = api; }
  if (typeof document !== "undefined") { api._initWhenReady(); }
})(typeof self !== "undefined" ? self : (typeof globalThis !== "undefined" ? globalThis : this), function () {

  // ───────── pure logic (also unit-tested under node) ─────────

  var ACTIVE = "active";          // a node is live while its status reads this (shared with the writer)
  var PENDING = "pending";        // a triage proposal awaits human disposition while its status reads this

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

  // Latest status per triage id wins (mirrors research-scope/triage.pending()).
  function foldTriage(records) {
    var latest = {};
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r && r.id != null) { latest[r.id] = r; }
    }
    var pending = [];
    var disposed = [];
    Object.keys(latest).forEach(function (id) {
      if (latest[id].status === PENDING) { pending.push(latest[id]); }
      else { disposed.push(latest[id]); }
    });
    pending.sort(function (a, b) { return byKey(a.id, b.id); });
    disposed.sort(function (a, b) { return byKey(a.id, b.id); });
    return { pending: pending, disposed: disposed };
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
    tab: "active",
    selection: null,            // { kind: "node"|"txn"|"triage", id: "..." }
    transitionsPath: "../outputs/_scope/transitions.jsonl",
    triagePath: "../outputs/_scope/triage.jsonl",
    prevSig: null,
    data: null,                 // last good { tStatus, records, errors, projection, latest, triage }
    lastRefresh: "-",
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

  function renderYardstick(node) {
    var yard = (node && node.yardstick) || {};
    var keys = Object.keys(yard);
    if (!keys.length) { return '<p class="unmeasured">No yardstick fields declared.</p>'; }
    return keys.map(function (k) {
      return '<div class="scope-field"><div class="k">' + esc(humanizeKey(k)) + "</div>" +
        renderValue(yard[k]) + "</div>";
    }).join("");
  }

  function statusChip(status) {
    var s = status || "unknown";
    return '<span class="chip" data-status="' + esc(s) + '">' + esc(s) + "</span>";
  }

  // ── tree (Active Scope) ──

  function nodeCardHtml(id, tree, depth) {
    var node = tree.active[id];
    var children = tree.childrenOf[id] || [];
    var selected = state.selection && state.selection.kind === "node" && state.selection.id === id;
    var head = [
      '<div class="scope-node-head">',
      "<div>",
      '<div class="k">' + esc(node.level || "node") + "</div>",
      "<h3>" + esc(id) + "</h3>",
      "</div>",
      statusChip(node.status),
      "</div>",
    ].join("");
    var summary = renderYardstick(node);
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
      '<div class="scope-node-fields">' + summary + "</div>",
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

  function proposalHtml(item) {
    var selected = state.selection && state.selection.kind === "triage" && state.selection.id === item.id;
    var rows = Object.keys(item).filter(function (k) { return k !== "id" && k !== "status"; })
      .map(function (k) {
        return '<div class="k">' + esc(humanizeKey(k)) + "</div><div>" + renderValue(item[k]) + "</div>";
      }).join("");
    return [
      '<article class="scope-node scope-proposal"' + (selected ? ' data-selected="true"' : "") +
        ' data-select-triage="' + esc(item.id) + '" tabindex="0" role="button">',
      '<div class="scope-node-head"><div><div class="k">Proposal</div><h3>' + esc(item.id) + "</h3></div>" +
        statusChip(item.status || PENDING) + "</div>",
      rows ? '<div class="kv-grid">' + rows + "</div>" : '<p class="unmeasured">No proposal fields recorded.</p>',
      "</article>",
    ].join("");
  }

  function renderTriage(panel, data) {
    var pending = data.triage.pending;
    if (!pending.length) {
      panel.innerHTML = '<div class="empty-state">No pending scope proposals. The agent may propose ' +
        "changes here; only the user disposes them.</div>";
      return;
    }
    panel.innerHTML = '<p class="scope-note">These are suggestions awaiting your disposition. They are ' +
      "<strong>not</strong> active scope.</p>" +
      '<div class="scope-forest">' + pending.map(proposalHtml).join("") + "</div>";
  }

  // ── history ──

  function renderHistory(panel, data) {
    if (!data.records.length) {
      panel.innerHTML = '<div class="empty-state">No transitions recorded yet.</div>';
      return;
    }
    var groups = historyByNode(data.records);
    var ids = Object.keys(groups).sort(byKey);
    panel.innerHTML = ids.map(function (id) {
      var items = groups[id].map(function (r) {
        var selected = state.selection && state.selection.kind === "txn" && state.selection.id === r.txn_id;
        var meta = [];
        if (r.cause) { meta.push("<p class='card-text'>" + esc(r.cause) + "</p>"); }
        if (r.trigger) { meta.push("<p class='card-text'><b>Trigger:</b> " + esc(r.trigger) + "</p>"); }
        return [
          '<div class="timeline-item">',
          '<div class="when">v' + esc(r.scope_version != null ? r.scope_version :
            (r.node && r.node.version != null ? r.node.version : "?")) + "</div>",
          '<div class="dot-col"><span class="dot"></span><span class="line"></span></div>',
          '<div class="timeline-body scope-history-row' + (selected ? " is-selected" : "") +
            '" data-select-txn="' + esc(r.txn_id || "") + '" tabindex="0" role="button">',
          "<h3>" + esc(r.op || "transition") + "</h3>",
          '<p class="scope-history-txn"><code>' + esc(r.txn_id || "-") + "</code></p>",
          meta.join(""),
          "</div>",
          "</div>",
        ].join("");
      }).join("");
      return '<section class="scope-history-group"><h2 class="scope-history-head"><code>' + esc(id) +
        '</code></h2><div class="timeline">' + items + "</div></section>";
    }).join("");
  }

  // ── raw log ──

  function renderRaw(panel, data) {
    var parts = [];
    if (data.errors.length) {
      parts.push('<div class="notice"><strong>Parse errors</strong><ul class="scope-list">' +
        data.errors.map(function (e) {
          return "<li>line " + e.line + ": " + esc(e.message) + "</li>";
        }).join("") + "</ul></div>");
    }
    if (!data.records.length && !data.errors.length) {
      panel.innerHTML = '<div class="empty-state">No records to show.</div>';
      return;
    }
    var body = data.records.map(function (r) {
      return esc(JSON.stringify(r, null, 2));
    }).join("\n\n");
    parts.push('<div class="code-box"><code>' + body + "</code></div>");
    panel.innerHTML = parts.join("");
  }

  // ── detail drawer ──

  function linkedPackages(nodeId) {
    var pkgs = (typeof window !== "undefined" && window.RESEARCH_PACKAGES) || [];
    return pkgs.filter(function (p) {
      if (p.sourceScopeNode === nodeId) { return true; }
      return (p.sourceScopeMilestones || []).some(function (m) { return m && m.id === nodeId; });
    });
  }

  function pkgHref(p) {
    if (p.detailPath) { return p.detailPath; }
    return "packages/" + encodeURIComponent(p.id) + "/index.html";
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
      ["Provenance", node.provenance ? "<code>" + esc(node.provenance) + "</code>" : '<span class="unmeasured">-</span>'],
    ];
    var prov = [
      ["Latest txn", rec.txn_id ? "<code>" + esc(rec.txn_id) + "</code>" : '<span class="unmeasured">-</span>'],
      ["Op", esc(rec.op || "-")],
      ["Gate", esc(rec.gate || "-")],
      ["Trigger", rec.trigger ? esc(rec.trigger) : '<span class="unmeasured">-</span>'],
      ["Cause", rec.cause ? esc(rec.cause) : '<span class="unmeasured">-</span>'],
    ];
    ["invalidates", "reopens", "dial_revert"].forEach(function (k) {
      if (rec[k] && rec[k].length) { prov.push([humanizeKey(k), renderValue(rec[k])]); }
    });
    var links = linkedPackages(id);
    var linkHtml = links.length
      ? '<ul class="scope-list">' + links.map(function (p) {
          return '<li><a href="' + esc(pkgHref(p)) + '">' + esc(p.name || p.id) + "</a></li>";
        }).join("") + "</ul>"
      : '<span class="unmeasured">No package links found.</span>';
    return [
      kvBlock(rows),
      '<div class="scope-drawer-section"><div class="scope-drawer-label">Yardstick</div>' +
        renderYardstick(node) + "</div>",
      '<div class="scope-drawer-section"><div class="scope-drawer-label">Latest transition</div>' +
        kvBlock(prov) + "</div>",
      '<div class="scope-drawer-section"><div class="scope-drawer-label">Linked packages</div>' +
        linkHtml + "</div>",
    ].join("");
  }

  function drawerForTxn(txnId, data) {
    var rec = null;
    for (var i = 0; i < data.records.length; i++) {
      if (data.records[i].txn_id === txnId) { rec = data.records[i]; break; }
    }
    if (!rec) { return '<p class="unmeasured">Transition ' + esc(txnId) + " not found.</p>"; }
    var rows = [
      ["Txn id", "<code>" + esc(rec.txn_id) + "</code>"],
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
      rec.node
        ? '<div class="scope-drawer-section"><div class="scope-drawer-label">Node snapshot</div>' +
          renderYardstick(rec.node) + "</div>"
        : "",
    ].join("");
  }

  function drawerForTriage(id, data) {
    var item = null;
    data.triage.pending.concat(data.triage.disposed).forEach(function (p) {
      if (p.id === id) { item = p; }
    });
    if (!item) { return '<p class="unmeasured">Proposal ' + esc(id) + " not found.</p>"; }
    var rows = Object.keys(item).map(function (k) { return [humanizeKey(k), renderValue(item[k])]; });
    return '<p class="scope-note">A proposal is a suggestion, never active scope.</p>' + kvBlock(rows);
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
    else if (sel.kind === "txn") { body = drawerForTxn(sel.id, data); }
    else if (sel.kind === "triage") { body = drawerForTriage(sel.id, data); }
    drawer.innerHTML = '<div class="scope-drawer-head">Detail</div>' + body;
  }

  // ── health strip + tabs ──

  function renderHealth(data) {
    var strip = $("[data-section='health']");
    if (!strip) { return; }
    var latestTxn = data.records.length ? (data.records[data.records.length - 1].txn_id || "-") : "-";
    var latestVer = "-";
    data.records.forEach(function (r) {
      var v = r.scope_version != null ? r.scope_version : (r.node && r.node.version);
      if (typeof v === "number" && (latestVer === "-" || v > latestVer)) { latestVer = v; }
    });
    var srcState = data.tStatus === "ok" ? "ok" :
      (data.tStatus === "empty" ? "empty" : (data.tStatus === "missing" ? "missing" : "unreachable"));
    var cells = [
      ["Scope source", "<span class='hint'>" + esc(state.transitionsPath) + "</span>", srcState],
      ["Latest version", "v" + esc(latestVer), null],
      ["Latest txn", "<span class='hint'>" + esc(latestTxn) + "</span>", null],
      ["Pending proposals", esc(data.triage.pending.length), data.triage.pending.length ? "warn" : null],
      ["Parse errors", esc(data.errors.length), data.errors.length ? "error" : null],
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
    var parsed = parseJsonl(transitions.text);
    var triageParsed = parseJsonl(triageRes.text);
    return {
      tStatus: transitions.status,
      records: parsed.records,
      errors: parsed.errors,
      projection: foldTransitions(parsed.records),
      latest: latestRecords(parsed.records),
      triage: foldTriage(triageParsed.records),
    };
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
    if (txn) { select("txn", txn.getAttribute("data-select-txn")); return; }
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
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    setTab(state.tab);
    refresh();
    setInterval(refresh, POLL_MS);
  }

  logic._initWhenReady = initWhenReady;
  return logic;
});
