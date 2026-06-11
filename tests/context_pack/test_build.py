"""Phase 0 — the I/O loader + CLI: read real stores, write pack artifacts."""
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))

import context_pack.build as build  # noqa: E402
import ensure_dashboard  # noqa: E402
import scope_ssot  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node required to read JS data")


_PACKAGES_JS = '''window.RESEARCH_PACKAGES = [
  { id: "2026-06-03-retrieval-v2", name: "Retrieval V2", category: "in-progress",
    status: "CONTEXT_LOADED", sourceScopeNode: "dir/retrieval-v2",
    activeGate: "R@1>=48", primaryMetricVsGate: "R@1 vs 48", nextRoute: "run P0",
    methodsTried: [] },
  { id: "2026-05-01-old", name: "Old", category: "fail", status: "ARCHIVED",
    terminationMessage: "did not clear",
    methodsTried: [
      { method: "hard-negative mining", hypothesis: "mining lifts R@1", gate: "R@1>=48",
        measured: "R@1=44", verdict: "FAIL",
        evidencePath: "packages/2026-05-01-old/results.html#m1" } ] },
  { id: "2026-04-01-win", name: "Win", category: "success", status: "ADOPTED",
    terminationMessage: "adopted", adoptionPath: "models/encoder.py#L40",
    methodsTried: [
      { method: "dual-encoder", hypothesis: "dual beats CLIP", gate: "R@1>=48",
        measured: "R@1=51", verdict: "PASS",
        evidencePath: "packages/2026-04-01-win/results.html#w1" } ] },
];
'''

def _append_registry_rows(root, rows):
    """Append rows to the scaffolded data/rules.js (keeps the universal mirror)."""
    rules_js = root / "data" / "rules.js"
    prefix = "window.RESEARCH_RULES = "
    existing = json.loads(rules_js.read_text(encoding="utf-8")[len(prefix):].rstrip().rstrip(";"))
    rules_js.write_text(prefix + json.dumps(existing + rows) + ";\n", encoding="utf-8")


def _setup(tmp_path):
    root = tmp_path / "research_html"
    ensure_dashboard.ensure_dashboard(root, force=False)
    (root / "data" / "research-packages.js").write_text(_PACKAGES_JS, encoding="utf-8")
    (root / "packages" / "2026-05-01-old").mkdir(parents=True, exist_ok=True)

    # direction node + scope log
    log = tmp_path / "outputs" / "_scope" / "transitions.jsonl"
    node = {
        "id": "dir/retrieval-v2", "level": "direction", "parents": ["project/main"], "version": 3,
        "status": "ACTIVE",
        "yardstick": {"hypothesis": "Contrastive retrieval improves zero-shot Recall@1",
                      "metric": {"name": "Recall@1", "dir": "higher"},
                      "baselines": ["CLIP=42.3"], "success_predicate": "Recall@1 >= 48"},
    }
    scope_ssot.propose_transition(node, op="create", gate="USER_CROSS_MODEL_AUDIT", log_path=log)

    # learned project rule + package lesson rows in the unified registry
    _append_registry_rows(root, [
        {"id": "PRJ-reproduce-baseline", "level": "project", "kind": "constraint",
         "title": "Reproduce the baseline", "text": "Always reproduce the baseline before claiming a lift.",
         "rationale": "validity", "source": "user", "origin": "user",
         "status": "ACTIVE", "addedAt": "2026-06-04"},
        {"id": "2026-05-01-old#mining-temperature", "level": "package", "pkg": "2026-05-01-old",
         "kind": "lesson", "title": "Mining needs temperature scaling",
         "text": "Hard-negative mining diverges without temperature scaling above 0.1.",
         "rationale": "insight-temp", "source": "analysis", "origin": "user",
         "status": "ACTIVE", "addedAt": "2026-06-04"},
    ])
    banl = tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "ideate" / "banlist.json"
    banl.parent.mkdir(parents=True, exist_ok=True)
    banl.write_text(json.dumps([{"id": "hyp-1", "kind": "idea",
                                 "hypothesis": "re-rank with a cross-encoder",
                                 "failed_on_metric": "Recall@1"}]), encoding="utf-8")
    src = tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "lit" / "sources.json"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(json.dumps({"src-001": {"source_id": "src-001", "title": "Dense Passage Retrieval",
                                           "url": "https://arxiv.org/abs/2004.04906",
                                           "excerpt": "DPR uses dual encoders."}}), encoding="utf-8")
    return root, log


def test_build_writes_full_pack_and_durable_core(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)

    build.build("research_html", "2026-06-03-retrieval-v2",
                transitions_path=str(log), generated_at="2026-06-04T00:00:00Z")

    md = (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.md").read_text(encoding="utf-8")
    pj = json.loads((tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").read_text(encoding="utf-8"))
    core_js = (root / "data" / "context-core.js").read_text(encoding="utf-8")

    # full pack carries everything: direction + cross-package failures + overlay
    assert "Contrastive retrieval improves zero-shot Recall@1" in md
    assert "hard-negative mining" in md                                  # cross-package failure
    assert "temperature scaling" in md                                   # package lesson row from the registry
    assert "Always reproduce the baseline" in md                         # learned rule
    assert "cross-encoder" in md                                         # banlist overlay
    assert "Dense Passage Retrieval" in md                               # papers overlay
    assert pj["stamp"]["scope_version"] == 3

    # durable core is direction-independent: cross-package knowledge only, NO overlay
    assert core_js.startswith("window.RESEARCH_CONTEXT_CORE")
    assert "hard-negative mining" in core_js
    assert "Always reproduce the baseline" in core_js
    assert "Dense Passage Retrieval" not in core_js                      # papers are overlay, not core
    assert "Contrastive retrieval improves" not in core_js               # direction is overlay, not core


def test_build_surfaces_knowledge_registries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    data = root / "data"
    (data / "papers.jsonl").write_text(
        json.dumps({"id": "dpr2020", "title": "Dense Passage Retrieval", "url": "http://x"}) + "\n",
        encoding="utf-8")
    (data / "edges.jsonl").write_text(
        json.dumps({"from": "paper:dpr2020", "to": "paper:ours", "type": "EXTENDS", "evidence": "sec3"}) + "\n",
        encoding="utf-8")
    (data / "gaps.jsonl").write_text(
        json.dumps({"id": "G1", "summary": "no zero-shot eval", "status": "open"}) + "\n",
        encoding="utf-8")

    build.build("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                generated_at="2026-06-04T00:00:00Z")

    md = (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.md").read_text(encoding="utf-8")
    core_js = (root / "data" / "context-core.js").read_text(encoding="utf-8")
    for needle in ("Dense Passage Retrieval", "EXTENDS", "no zero-shot eval"):
        assert needle in md
        assert needle in core_js  # registries are cross-package → in the durable core too


def test_build_degrades_gracefully_without_optional_stores(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "research_html"
    ensure_dashboard.ensure_dashboard(root, force=False)
    (root / "data" / "research-packages.js").write_text(_PACKAGES_JS, encoding="utf-8")
    log = tmp_path / "outputs" / "_scope" / "transitions.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("", encoding="utf-8")  # no direction

    # no project/package rule rows, no banlist, no sources — must still build
    build.build("research_html", "2026-06-03-retrieval-v2",
                transitions_path=str(log), generated_at="2026-06-04T00:00:00Z")

    md = (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.md").read_text(encoding="utf-8")
    assert "hard-negative mining" in md          # cross-package failure still compiled from packages
    assert (root / "data" / "context-core.js").exists()


def test_cli_main(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    rc = build.main(["--pkg", "2026-06-03-retrieval-v2", "--transitions", str(log)])
    assert rc == 0
    assert (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").exists()


def test_ensure_fresh_rebuilds_only_when_scope_advanced(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    build.build("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                generated_at="t0")

    # fresh (scope unchanged) → no rebuild, artifact untouched
    assert build.ensure_fresh("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                              generated_at="t1") is False
    pj = json.loads((tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").read_text())
    assert pj["stamp"]["generated_at"] == "t0"

    # advance the scope (a metric revise bumps the direction version) → stale → rebuild
    node = scope_ssot.fold(scope_ssot.read_log(str(log)))["dir/retrieval-v2"]
    node["version"] = 4
    scope_ssot.propose_transition(node, op="revise", gate="USER_CROSS_MODEL_AUDIT", log_path=log)
    assert build.ensure_fresh("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                              generated_at="t2") is True
    pj2 = json.loads((tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").read_text())
    assert pj2["stamp"]["scope_version"] == 4 and pj2["stamp"]["generated_at"] == "t2"


def test_cli_if_stale_builds_then_skips(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    assert build.main(["--pkg", "2026-06-03-retrieval-v2", "--transitions", str(log),
                       "--if-stale"]) == 0
    assert "rebuilt" in capsys.readouterr().out
    # second call: already fresh, no rebuild
    assert build.main(["--pkg", "2026-06-03-retrieval-v2", "--transitions", str(log),
                       "--if-stale"]) == 0
    assert "already fresh" in capsys.readouterr().out


def test_ensure_fresh_builds_when_pack_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    assert build.ensure_fresh("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                              generated_at="t0") is True
    assert (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").exists()


def test_build_py_runs_as_script(tmp_path, monkeypatch):
    """The SKILL prose invokes `python lib/context_pack/build.py` — it must self-bootstrap sys.path."""
    import subprocess as sp
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    rc = sp.run([sys.executable, str(ROOT / "lib" / "context_pack" / "build.py"),
                 "--pkg", "2026-06-03-retrieval-v2", "--transitions", str(log)],
                capture_output=True, text=True)
    assert rc.returncode == 0, rc.stderr
    assert (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.md").exists()
