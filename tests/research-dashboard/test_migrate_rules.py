"""migrate_rules: lift bindingRules[], analysis <li>s, rules.md, profile constraints into the registry."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[2] / "skills" / "research-dashboard"
          / "assets" / "dashboard" / "scripts" / "migrate_rules.py")

PKGS_JS = """window.RESEARCH_PROJECT_PROFILE = {
  name: "Demo", constraints: ["Budget: 8 GPU-h per run"],
};
window.RESEARCH_PACKAGES = [
  { id: "2026-01-01-demo", category: "in-progress", status: "IMPLEMENTING",
    bindingRules: [{ rule: "one notebook per figure", rationale: "repro", addedAt: "2026-01-02" }] },
];
"""

ANALYSIS = ('<html><body><ol class="rules-list" data-list="rules">'
            '<li class="card-text" id="rule-no-mock">Never mock metrics.</li>'
            '</ol></body></html>')


def _tree(tmp_path):
    root = tmp_path / "research_html"
    (root / "data").mkdir(parents=True)
    (root / "data" / "research-packages.js").write_text(PKGS_JS)
    (root / "data" / "rules.js").write_text("window.RESEARCH_RULES = [];\n")
    pkg = root / "packages" / "2026-01-01-demo"
    pkg.mkdir(parents=True)
    (pkg / "analysis.html").write_text(ANALYSIS)
    learned = tmp_path / "outputs" / "_learned"
    learned.mkdir(parents=True)
    (learned / "rules.md").write_text("- Never train on eval\n")
    return root


def _run(tmp_path, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), "--root", "research_html", *extra],
                          cwd=tmp_path, capture_output=True, text=True)


def _rules(root):
    return json.loads((root / "data" / "rules.js").read_text()
                      [len("window.RESEARCH_RULES = "):].rstrip().rstrip(";"))


def test_dry_run_reports_without_writing(tmp_path):
    root = _tree(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "4 rows" in r.stdout  # 1 binding + 1 lesson + 1 learned + 1 constraint
    assert _rules(root) == []


def test_write_migrates_and_strips_sources(tmp_path):
    root = _tree(tmp_path)
    r = _run(tmp_path, "--write")
    assert r.returncode == 0, r.stderr
    rows = _rules(root)
    ids = {row["id"] for row in rows}
    assert {"2026-01-01-demo#one-notebook-per-figure", "2026-01-01-demo#no-mock",
            "PRJ-never-train-on-eval", "PRJ-budget-8-gpu-h-per-run"} <= ids
    assert all(row["origin"] == "migration" for row in rows)
    pkgs = (root / "data" / "research-packages.js").read_text()
    assert "bindingRules" not in pkgs and "constraints" not in pkgs
    assert not (tmp_path / "outputs" / "_learned" / "rules.md").exists()


def test_idempotent_rerun_is_noop(tmp_path):
    _tree(tmp_path)
    _run(tmp_path, "--write")
    r = _run(tmp_path, "--write")
    assert r.returncode == 0 and "0 rows" in r.stdout


def test_binding_rules_stay_attached_to_their_package(tmp_path):
    root = tmp_path / "research_html"
    (root / "data").mkdir(parents=True)
    (root / "data" / "rules.js").write_text("window.RESEARCH_RULES = [];\n")
    (root / "data" / "research-packages.js").write_text("""window.RESEARCH_PACKAGES = [
  { id: "pkg-a", category: "in-progress", status: "IMPLEMENTING" },
  { id: "pkg-b", category: "in-progress", status: "IMPLEMENTING",
    bindingRules: [{ rule: "bind only b", rationale: "scope", addedAt: "2026-06-11" }] },
];
""")

    r = _run(tmp_path, "--write")
    assert r.returncode == 0, r.stderr
    ids = {row["id"] for row in _rules(root)}
    assert "pkg-b#bind-only-b" in ids
    assert "pkg-a#bind-only-b" not in ids


def test_missing_registry_is_treated_as_empty_on_dry_run(tmp_path):
    root = tmp_path / "research_html"
    (root / "data").mkdir(parents=True)
    (root / "data" / "research-packages.js").write_text(PKGS_JS)

    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "2 rows" in r.stdout
    assert not (root / "data" / "rules.js").exists()
