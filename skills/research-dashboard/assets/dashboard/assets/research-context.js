// Renders the compiled Context Pack core (data/context-core.js → window.RESEARCH_CONTEXT_CORE)
// into #context-root. Derived, read-only: this view never mutates a store.
(function () {
  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function render() {
    var root = document.getElementById("context-root");
    if (!root) return;
    var data = window.RESEARCH_CONTEXT_CORE || {};
    var stamp = data.stamp || {};
    var sections = data.sections || [];
    var html = "";

    html += '<p class="footer-note" data-card="context-stamp">scope_version=' +
      esc(stamp.scope_version !== undefined ? stamp.scope_version : "—") +
      " &middot; generated_at=" + esc(stamp.generated_at || "—") +
      " &middot; truncated=" + esc(stamp.truncated) + "</p>";

    if (!sections.length) {
      html += '<p class="context-empty">No compiled context yet. Run the package execution loop — it ' +
        "compiles the Context Pack at context-load — to populate this view.</p>";
    } else {
      sections.forEach(function (sec) {
        html += '<article class="context-card" data-key="' + esc(sec.key) + '"><h2>' +
          esc(sec.title) + (sec.protected ? " <span data-pin=\"core\">(core)</span>" : "") +
          "</h2><ul>";
        (sec.lines || []).forEach(function (ln) { html += "<li>" + esc(ln) + "</li>"; });
        html += "</ul></article>";
      });
    }
    root.innerHTML = html;
  }

  window.__researchRenderers = window.__researchRenderers || [];
  window.__researchRenderers.push(render);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render);
  } else {
    render();
  }
})();
