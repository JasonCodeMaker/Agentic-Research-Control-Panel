"""Phases 4-6 — project-level knowledge registries (papers / edges / gaps) via research-op."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

import registry  # noqa: E402

CLI = ROOT / "skills" / "research-op" / "scripts" / "research_op.py"


# ── registry.add — validators + dedup (pure) ────────────────────────────────

def test_add_paper_appends_then_dedups(tmp_path):
    root = str(tmp_path / "research_html")
    s1, rec, path = registry.add("paper", {"id": "dpr2020", "title": "DPR", "url": "u"}, root=root)
    assert s1 == "added" and rec["id"] == "dpr2020"
    s2, _, _ = registry.add("paper", {"id": "dpr2020", "title": "DPR again"}, root=root)
    assert s2 == "duplicate"
    assert len(path.read_text().splitlines()) == 1


def test_paper_requires_id_and_title(tmp_path):
    root = str(tmp_path / "research_html")
    for bad in ({"title": "no id"}, {"id": "x"}):
        try:
            registry.add("paper", bad, root=root)
            assert False, "expected RegistryReject"
        except registry.RegistryReject as e:
            assert e.rule in ("paper-id-required", "paper-title-required")


def test_add_edge_validates_type_and_dedups(tmp_path):
    root = str(tmp_path / "research_html")
    s1, rec, _ = registry.add("edge", {"from": "paper:a", "to": "paper:b", "type": "extends"}, root=root)
    assert s1 == "added" and rec["type"] == "extends"
    s2, _, _ = registry.add("edge", {"from": "paper:a", "to": "paper:b", "type": "extends"}, root=root)
    assert s2 == "duplicate"
    try:
        registry.add("edge", {"from": "a", "to": "b", "type": "bogus"}, root=root)
        assert False
    except registry.RegistryReject as e:
        assert e.rule == "edge-type-unknown"


def test_edge_requires_endpoints(tmp_path):
    root = str(tmp_path / "research_html")
    try:
        registry.add("edge", {"from": "a", "type": "extends"}, root=root)
        assert False
    except registry.RegistryReject as e:
        assert e.rule == "edge-endpoints-required"


def test_add_gap_requires_id_and_summary(tmp_path):
    root = str(tmp_path / "research_html")
    s1, rec, _ = registry.add("gap", {"id": "G1", "summary": "no zero-shot eval"}, root=root)
    assert s1 == "added" and rec["status"] == "open"
    try:
        registry.add("gap", {"id": "G2"}, root=root)
        assert False
    except registry.RegistryReject as e:
        assert e.rule == "gap-summary-required"


def test_unknown_target_rejected(tmp_path):
    try:
        registry.add("widget", {"id": "x"}, root=str(tmp_path / "research_html"))
        assert False
    except registry.RegistryReject as e:
        assert e.rule == "unknown-target"


# ── research-op CLI integration (uses the tmp_package fixture from conftest) ──

def _run(args):
    return subprocess.run([sys.executable, str(CLI)] + args, capture_output=True, text=True)


def test_cli_registry_add_paper(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "registry-add", "--target", "paper",
              "--payload", json.dumps({"id": "dpr2020", "title": "Dense Passage Retrieval",
                                       "url": "https://arxiv.org/abs/2004.04906"})])
    assert r.returncode == 0, r.stderr
    assert "registry-add added" in r.stdout
    store = tmp_package / "research_html" / "data" / "papers.jsonl"
    assert store.exists() and "Dense Passage Retrieval" in store.read_text()
    # audit line recorded (project-level op still leaves a receipt)
    audit = (tmp_package / "outputs" / "test-pkg" / "_actions.jsonl").read_text()
    assert '"op": "registry-add"' in audit and '"validation": "passed"' in audit


def test_cli_registry_add_rejects_bad_edge_type(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "registry-add", "--target", "edge",
              "--payload", json.dumps({"from": "paper:a", "to": "paper:b", "type": "bogus"})])
    assert r.returncode == 2
    env = json.loads(r.stdout)
    assert env["rejected"] is True and env["rule"] == "edge-type-unknown"
    # reject-before-write: no store file created
    assert not (tmp_package / "research_html" / "data" / "edges.jsonl").exists()
    audit = (tmp_package / "outputs" / "test-pkg" / "_actions.jsonl").read_text()
    assert '"validation": "rejected"' in audit
