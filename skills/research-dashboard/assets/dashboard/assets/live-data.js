/* Shared live-data poller. Generalizes live.html: a static shell declares its
 * data files via <script src="data/*.js"> tags; this module re-fetches those
 * files on a timer, and only when a file's content changed it re-evaluates the
 * file (the data files assign window.X = ..., so re-eval is safe) and invokes
 * every repaint function registered on window.__researchRenderers. No page
 * reload is involved, so scroll/selection survive. Pure helpers are exported
 * for node tests; the browser bootstrap is guarded and skipped under node. */
(function () {
  "use strict";

  var POLL_MS = 3000;

  // FNV-1a 32-bit. Deterministic, dependency-free.
  function hashText(text) {
    var h = 2166136261;
    for (var i = 0; i < text.length; i++) {
      h ^= text.charCodeAt(i);
      h = (h * 16777619) >>> 0;
    }
    return String(h);
  }

  // True for a research data file path: data/<name>.js, possibly with ../ prefix
  // or a ?query, but NOT for paths like mydata/x.js or assets/research.js.
  function isDataSource(src) {
    return /(^|\/)data\/[^?]+\.js(\?|$)/.test(src);
  }

  function dataSourceUrls(srcList) {
    return srcList.filter(isDataSource);
  }

  if (typeof document !== "undefined" && typeof window !== "undefined" && typeof fetch === "function") {
    var lastHash = {};
    var started = false;

    function collectSourceUrls() {
      var urls = [];
      var nodes = document.querySelectorAll("script[src]");
      Array.prototype.forEach.call(nodes, function (node) {
        var raw = node.getAttribute("src") || "";
        if (isDataSource(raw)) {
          urls.push(node.src || raw); // node.src resolves to an absolute URL
        }
      });
      return urls;
    }

    function callRenderers() {
      var fns = window.__researchRenderers || [];
      fns.forEach(function (fn) {
        try { fn(); } catch (err) { /* keep last good render */ }
      });
    }

    function refreshOne(url) {
      return fetch(url, { cache: "no-store" })
        .then(function (res) { return res.ok ? res.text() : null; })
        .then(function (text) {
          if (text == null) return false;
          var h = hashText(text);
          if (lastHash[url] === h) return false;       // unchanged
          var firstSeen = !(url in lastHash);
          lastHash[url] = h;
          if (firstSeen) return false;                 // baseline; page already painted on load
          try { (0, eval)(text); return true; }        // re-assign window.X globals in global scope
          catch (err) { return false; }
        })
        .catch(function () { return false; });
    }

    function poll() {
      var urls = collectSourceUrls();
      Promise.all(urls.map(refreshOne)).then(function (changed) {
        if (changed.some(Boolean)) callRenderers();
      });
    }

    function start() {
      if (started) return;
      started = true;
      poll();
      window.setInterval(poll, POLL_MS);
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", start);
    } else {
      start();
    }
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      hashText: hashText,
      isDataSource: isDataSource,
      dataSourceUrls: dataSourceUrls,
      POLL_MS: POLL_MS,
    };
  }
}());
