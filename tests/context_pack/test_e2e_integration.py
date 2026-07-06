"""End-to-end: the whole wiki-integration composes.

real research-op registry writes → build Context Pack agent artifacts.
Proves the mutation surface and assembler line up on the same data.
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
from tests.scope_fixtures import direction_node  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node required")

OP = ROOT / "skills" / "research-op" / "scripts" / "research_op.py"

_PACKAGES_JS = '''window.RESEARCH_PACKAGES = [
  { id: "2026-06-03-active", name: "Active", category: "in-progress", status: "CONTEXT_LOADED",
    sourceDirection: "dir/active", activeGate: "g", primaryMetricVsGate: "m vs g", nextRoute: "run",
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
        direction_node("dir/active", metric={"name": "R@1"}),
        op="create", gate="USER_CROSS_MODEL_AUDIT", log_path=log)
    # Land a project rule through the real single entry (research-op rule target).
    assert _op(tmp_path, "--pkg", "_project", "--op", "insert", "--target", "rule",
               "--payload", json.dumps({"level": "project", "kind": "constraint",
                                        "slug": "reproduce-baseline-first",
                                        "title": "Reproduce the baseline first",
                                        "text": "reproduce the baseline first",
                                        "rationale": "validity", "addedAt": "2026-06-04",
                                        "ack": "approved in test"})).returncode == 0

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

    # Phase 0/1: build the Context Pack agent artifacts
    build.build("research_html", "2026-06-03-active", transitions_path=str(log),
                generated_at="2026-06-04T00:00:00Z")
    md = (tmp_path / "outputs" / "2026-06-03-active" / "context_pack.md").read_text(encoding="utf-8")
    payload = json.loads((tmp_path / "outputs" / "2026-06-03-active" / "context_pack.json").read_text(encoding="utf-8"))
    for needle in ("Adding supervised contrastive pretraining", "reproduce the baseline first", "mining",
                   "Dense Passage Retrieval", "EXTENDS", "no zero-shot eval"):
        assert needle in md, needle
    assert any(section["key"] == "failed_methods" for section in payload["sections"])
    assert not (root / "data" / "context-core.js").exists()
