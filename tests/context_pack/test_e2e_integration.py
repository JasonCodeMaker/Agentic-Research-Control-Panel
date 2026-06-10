"""End-to-end: the whole wiki-integration composes — Phases 0-6 together.

real research-op registry writes → build (Context Pack + durable core) → reflect cross-package
dead-end → context.html render. Proves the mutation surface, the assembler, the self-learning
detector, and the human surface all line up on the same data.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))

import context_pack.build as build  # noqa: E402
import ensure_dashboard  # noqa: E402
import scope_ssot  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node required")

OP = ROOT / "skills" / "research-op" / "scripts" / "research_op.py"
REFLECT = ROOT / "skills" / "research-reflect" / "scripts" / "reflect.py"
RENDER = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "assets" / "research-context.js"

_PACKAGES_JS = '''window.RESEARCH_PACKAGES = [
  { id: "2026-06-03-active", name: "Active", category: "in-progress", status: "CONTEXT_LOADED",
    sourceScopeNode: "dir/active", activeGate: "g", primaryMetricVsGate: "m vs g", nextRoute: "run",
    methodsTried: [] },
  { id: "2026-05-01-f1", name: "F1", category: "fail", status: "ARCHIVED", terminationMessage: "x",
    methodsTried: [ { method: "mining", hypothesis: "h1", gate: "g", measured: "m", verdict: "FAIL",
                      evidencePath: "packages/2026-05-01-f1/results.html#m1" } ] },
  { id: "2026-05-02-f2", name: "F2", category: "fail", status: "ARCHIVED", terminationMessage: "x",
    methodsTried: [ { method: "mining", hypothesis: "h2", gate: "g", measured: "m", verdict: "FAIL",
                      evidencePath: "packages/2026-05-02-f2/results.html#m1" } ] },
];
'''


def _op(tmp, *args):
    return subprocess.run([sys.executable, str(OP), *args], cwd=tmp, capture_output=True, text=True)


def test_full_wiki_integration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "research_html"
    ensure_dashboard.ensure_dashboard(root, force=False)
    (root / "data" / "research-packages.js").write_text(_PACKAGES_JS, encoding="utf-8")

    log = tmp_path / "outputs" / "_scope" / "transitions.jsonl"
    scope_ssot.propose_transition(
        {"id": "dir/active", "level": "direction", "parents": ["project/main"], "version": 1,
         "status": "ACTIVE", "yardstick": {"hypothesis": "active hypothesis", "metric": {"name": "R@1"},
                                           "baselines": ["b"], "success_predicate": "R@1>=48"}},
        op="create", gate="USER_CROSS_MODEL_AUDIT", log_path=log)
    learned = tmp_path / "outputs" / "_learned" / "rules.md"
    learned.parent.mkdir(parents=True, exist_ok=True)
    learned.write_text("- reproduce the baseline first\n", encoding="utf-8")

    # Phase 4/5/6: real mutation surface — research-op writes the durable registries
    assert _op(tmp_path, "--pkg", "2026-06-03-active", "--op", "registry-add", "--target", "paper",
               "--payload", json.dumps({"id": "dpr2020", "title": "Dense Passage Retrieval",
                                        "url": "http://x"})).returncode == 0
    assert _op(tmp_path, "--pkg", "2026-06-03-active", "--op", "registry-add", "--target", "edge",
               "--payload", json.dumps({"from": "paper:dpr2020", "to": "paper:ours",
                                        "type": "EXTENDS", "evidence": "sec3"})).returncode == 0
    assert _op(tmp_path, "--pkg", "2026-06-03-active", "--op", "registry-add", "--target", "gap",
               "--payload", json.dumps({"id": "G1", "summary": "no zero-shot eval"})).returncode == 0
    # reject-before-write still holds end-to-end
    assert _op(tmp_path, "--pkg", "2026-06-03-active", "--op", "registry-add", "--target", "edge",
               "--payload", json.dumps({"from": "a", "to": "b", "type": "bogus"})).returncode == 2

    # Phase 0/1: build the Context Pack + durable core
    build.build("research_html", "2026-06-03-active", transitions_path=str(log),
                learned_path=str(learned), generated_at="2026-06-04T00:00:00Z")
    md = (tmp_path / "outputs" / "2026-06-03-active" / "context_pack.md").read_text(encoding="utf-8")
    for needle in ("active hypothesis", "reproduce the baseline first", "mining",
                   "Dense Passage Retrieval", "EXTENDS", "no zero-shot eval"):
        assert needle in md, needle

    # Phase 3: reflect reads the pack's facts → cross-package dead-end (mining failed in 2 packages)
    pending = tmp_path / "outputs" / "2026-06-03-active" / "pending"
    r = subprocess.run([sys.executable, str(REFLECT), "--context-pack",
                        str(tmp_path / "outputs" / "2026-06-03-active" / "context_pack.json"),
                        "--pending-dir", str(pending), "--threshold", "2"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert any(f["kind"] == "CROSS_PACKAGE_DEAD_END" and f["method"] == "mining" for f in out["findings"])

    # Phase 2: the human surface renders the same durable core
    core_js = root / "data" / "context-core.js"
    script = f'''
      global.window = {{}};
      var captured = "";
      global.document = {{ readyState: "complete",
        getElementById: function (id) {{ return id === "context-root" ? {{ set innerHTML(v) {{ captured = v; }} }} : null; }},
        addEventListener: function () {{}} }};
      const fs = require("fs");
      eval(fs.readFileSync({json.dumps(str(core_js))}, "utf8"));
      eval(fs.readFileSync({json.dumps(str(RENDER))}, "utf8"));
      process.stdout.write(captured);
    '''
    rendered = subprocess.check_output(["node", "-e", script], text=True)
    assert "mining" in rendered and "Dense Passage Retrieval" in rendered and "no zero-shot eval" in rendered
