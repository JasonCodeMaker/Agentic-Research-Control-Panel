"""ensure_dashboard scaffolds data/rules.js and mirrors R/T cards into write-locked universal rows."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[2]
          / "skills" / "research-dashboard" / "scripts" / "ensure_dashboard.py")


def _scaffold(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path / "research_html")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return tmp_path / "research_html"


def _load(root):
    text = (root / "data" / "rules.js").read_text()
    return json.loads(text[len("window.RESEARCH_RULES = "):].rstrip().rstrip(";"))


def test_scaffold_writes_rules_js_with_universal_mirror(tmp_path):
    root = _scaffold(tmp_path)
    rules = _load(root)
    ids = {r["id"] for r in rules}
    assert {"R1", "R18", "T1", "T24"} <= ids
    r1 = next(r for r in rules if r["id"] == "R1")
    assert r1["level"] == "universal" and r1["origin"] == "mirror"
    assert r1["kind"] == "form" and r1["source"] == "rules/html-rules.html#R1"
    assert r1["title"]  # parsed from the card <h3 class="title">
    t1 = next(r for r in rules if r["id"] == "T1")
    assert t1["kind"] == "trust" and t1["source"] == "rules/trustworthy-research-rules.html#T1"


def test_rescaffold_preserves_non_mirror_rows(tmp_path):
    root = _scaffold(tmp_path)
    rules = _load(root)
    rules.append({"id": "PRJ-x", "level": "project", "kind": "constraint", "title": "x",
                  "text": "x", "rationale": "x", "source": "user", "origin": "user",
                  "status": "ACTIVE", "addedAt": "2026-06-11"})
    (root / "data" / "rules.js").write_text(
        "window.RESEARCH_RULES = " + json.dumps(rules) + ";\n")
    _scaffold(tmp_path)  # idempotent re-run refreshes the mirror only
    after = _load(root)
    assert any(r["id"] == "PRJ-x" for r in after)
    assert any(r["id"] == "R1" for r in after)


def test_refresh_chrome_overwrites_chrome_preserves_data(tmp_path):
    root = _scaffold(tmp_path)
    (root / "assets" / "research.js").write_text("// stale chrome")
    (root / "data" / "research-packages.js").write_text(
        "window.RESEARCH_PACKAGES = [{ id: 'keep' }];\n")
    r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), "--refresh-chrome"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "stale chrome" not in (root / "assets" / "research.js").read_text()
    assert "keep" in (root / "data" / "research-packages.js").read_text()


def test_refresh_chrome_preserves_rules_registry_rows(tmp_path):
    root = _scaffold(tmp_path)
    rules = _load(root)
    rules.append({"id": "PRJ-y", "level": "project", "kind": "constraint", "title": "y",
                  "text": "y", "rationale": "y", "source": "user", "origin": "user",
                  "status": "ACTIVE", "addedAt": "2026-06-11"})
    (root / "data" / "rules.js").write_text(
        "window.RESEARCH_RULES = " + json.dumps(rules) + ";\n")
    r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), "--refresh-chrome"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert any(row["id"] == "PRJ-y" for row in _load(root))


def test_malformed_rules_registry_is_not_clobbered(tmp_path):
    root = _scaffold(tmp_path)
    bad = "window.BAD_RULES = [{ id: 'PRJ-keep' }];\n"
    (root / "data" / "rules.js").write_text(bad)
    r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), "--refresh-chrome"],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert (root / "data" / "rules.js").read_text() == bad
