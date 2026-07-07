/* toc.js — client-side top-of-doc index + timeline for long package docs.
 *
 * A doc page that ships an empty `<nav class="docs-toc" data-docs-toc>` host gets a
 * top-of-page index built from its own h2/h3 headings plus an optional chronological
 * timeline built from dated sections. Nothing is authored per doc.
 *
 * Runs in two ways, covering both doc surfaces:
 *   - pushed onto window.__researchRenderers, so on docs/index.html (which loads
 *     research.js) it re-runs AFTER renderAll on every 3s live-data repaint and reads
 *     the freshly painted, data-driven group/doc headings;
 *   - bound to DOMContentLoaded, so the script-less doc-source leaf self-renders.
 *
 * It only ever writes its own [data-docs-toc] host innerHTML and back-fills id
 * attributes on heading/section wrappers so anchors resolve. It never rewrites the
 * docs-groups container that renderDocsIndex owns and writes no package state.
 */
(function () {
  "use strict";
  var DEFAULT_MIN_HEADINGS = 4; // below this a doc is short enough to skip the nav

  function slugify(text) {
    var el = (typeof document !== "undefined") ? document.createElement("div") : null;
    var s = text;
    if (el) { el.innerHTML = text; s = el.textContent || el.innerText || ""; }
    s = s.toLowerCase().replace(/&[a-z]+;/g, " ");
    s = s.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    return s || "section";
  }

  function firstHeading(el) {
    if (!el || !el.querySelectorAll) return null;
    var hs = el.querySelectorAll("h2, h3");
    for (var i = 0; i < hs.length; i++) {
      if (!(hs[i].closest && hs[i].closest("[data-docs-toc]"))) return hs[i];
    }
    return null;
  }

  function ensureId(headingEl, used) {
    // Prefer the heading's own id.
    if (headingEl.id) { used[headingEl.id] = true; return headingEl.id; }
    // Reuse a wrapping section/article anchor only when this heading is that wrapper's
    // OWN title (its first h2/h3). Otherwise many sibling headings inside one big
    // <section id="doc-body"> would all collapse onto the same container anchor.
    var titled = headingEl.closest ? headingEl.closest("section[id],article[id]") : null;
    if (titled && firstHeading(titled) === headingEl) { used[titled.id] = true; return titled.id; }
    var base = slugify(headingEl.textContent || "section");
    var id = base, n = 2;
    while (used[id]) { id = base + "-" + n; n++; }
    used[id] = true;
    // Anchor a fresh id on the wrapping section/article only when this heading titles
    // it; a shared container must not take an id derived from one of its many headings.
    var wrapper = headingEl.closest ? headingEl.closest("section,article") : null;
    var target = (wrapper && firstHeading(wrapper) === headingEl) ? wrapper : headingEl;
    if (!target.id) target.id = id;
    return id;
  }

  function htmlEscape(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function contentRoot() {
    // docs/index.html: the repainted groups live in #main-content.
    var main = (typeof document !== "undefined") ? document.getElementById("main-content") : null;
    if (main) return main;
    // doc-source leaf: scan the whole shell body region.
    return document.querySelector(".shell") || document.body;
  }

  function minHeadings(host) {
    var attr = host.getAttribute && host.getAttribute("data-docs-toc-min");
    var n = attr != null ? parseInt(attr, 10) : NaN;
    return (!isNaN(n) && n >= 0) ? n : DEFAULT_MIN_HEADINGS;
  }

  function buildIndex(root, used, min) {
    if (min == null) min = DEFAULT_MIN_HEADINGS;
    var heads = root.querySelectorAll("h2, h3");
    var items = [], i, h, id, tag, label;
    for (i = 0; i < heads.length; i++) {
      h = heads[i];
      if (h.closest && h.closest("[data-docs-toc]")) continue; // skip headings inside the host
      tag = h.tagName.toLowerCase();
      id = ensureId(h, used);
      label = h.textContent || id;
      items.push({ tag: tag, id: id, label: label });
    }
    if (items.length < min) return "";
    var lis = items.map(function (it) {
      var cls = it.tag === "h3" ? " class=\"docs-toc-sub\"" : "";
      return "<li" + cls + "><a href=\"#" + it.id + "\">" + htmlEscape(it.label) + "</a></li>";
    }).join("");
    return "<div class=\"docs-toc-section\"><p class=\"docs-toc-label\">On this page</p><ol class=\"docs-toc-list\">" + lis + "</ol></div>";
  }

  function parseDate(el) {
    // Priority: data-ts attr, then any YYYY-MM-DD in the element text.
    var ts = el.getAttribute && el.getAttribute("data-ts");
    if (ts && /^\d{4}-\d{2}-\d{2}/.test(ts)) return ts.slice(0, 10);
    var m = (el.textContent || "").match(/(\d{4}-\d{2}-\d{2})/);
    return m ? m[1] : null;
  }

  function buildTimeline(root, used) {
    var candidates = root.querySelectorAll("[data-ts], .timeline-entry, h2, h3");
    var entries = [], i, el, headingEl, date, id, label;
    for (i = 0; i < candidates.length; i++) {
      el = candidates[i];
      if (el.closest && el.closest("[data-docs-toc]")) continue;
      date = parseDate(el);
      if (!date) continue;
      // resolve the heading that labels this dated element
      headingEl = (el.tagName && /^H[23]$/.test(el.tagName)) ? el
                  : (el.querySelector ? el.querySelector("h2, h3") : null);
      if (!headingEl) continue;
      id = ensureId(headingEl, used);
      label = (headingEl.textContent || id).replace(/\s*\(?\d{4}-\d{2}-\d{2}.*?\)?\s*$/, "");
      entries.push({ date: date, id: id, label: label });
    }
    if (!entries.length) return "";
    entries.sort(function (a, b) { return a.date < b.date ? -1 : (a.date > b.date ? 1 : 0); });
    var rows = entries.map(function (e, idx) {
      var lineCls = (idx === entries.length - 1) ? "" : "line";
      return "<li class=\"timeline-item\">"
        + "<span class=\"when\">" + htmlEscape(e.date) + "</span>"
        + "<span class=\"dot-col\"><span class=\"dot\"></span><span class=\"" + lineCls + "\"></span></span>"
        + "<div class=\"timeline-body\"><a href=\"#" + e.id + "\">" + htmlEscape(e.label) + "</a></div>"
        + "</li>";
    }).join("");
    return "<div class=\"docs-toc-section\"><p class=\"docs-toc-label\">Timeline</p><ol class=\"timeline docs-toc-timeline\">" + rows + "</ol></div>";
  }

  function renderToc() {
    if (typeof document === "undefined") return;
    var host = document.querySelector("[data-docs-toc]");
    if (!host) return; // inert on every page without the host
    var root = contentRoot();
    if (!root) return;
    var used = {};
    var indexHtml = buildIndex(root, used, minHeadings(host));
    if (!indexHtml) { host.innerHTML = ""; return; } // below threshold -> paint nothing
    var timelineHtml = buildTimeline(root, used);
    host.innerHTML = indexHtml + timelineHtml;
  }

  if (typeof window !== "undefined") {
    window.__researchRenderers = window.__researchRenderers || [];
    window.__researchRenderers.push(renderToc);
    document.addEventListener("DOMContentLoaded", renderToc);
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { slugify: slugify, buildIndex: buildIndex, buildTimeline: buildTimeline, renderToc: renderToc };
  }
})();
