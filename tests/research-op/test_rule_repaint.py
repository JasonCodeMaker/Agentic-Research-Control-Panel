"""kind=lesson rows repaint analysis.html#rules from the registry (inventory→paint doctrine)."""

import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts" / "research_op.py"

ANALYSIS = """<html><body><main>
<section id="rules" data-section="rules">
  <ol class="rules-list" data-list="rules">
    <li><em>No rules recorded yet.</em></li>
  </ol>
</section>
</main></body></html>"""


def _run(args, cwd):
    return subprocess.run([sys.executable, str(CLI)] + args, cwd=cwd, capture_output=True, text=True)


def test_lesson_insert_repaints_analysis(tmp_package):
    pkg_dir = tmp_package / "research_html" / "packages" / "test-pkg"
    (pkg_dir / "analysis.html").write_text(ANALYSIS)
    (pkg_dir / "results.html").write_text("<html><td>PASS</td></html>")
    payload = json.dumps({"level": "package", "pkg": "test-pkg", "kind": "lesson",
                          "slug": "no-mock", "title": "No mocked metrics",
                          "text": "Never paste metrics without an artifact.",
                          "rationale": "T5", "addedAt": "2026-06-11"})
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "rule",
              "--payload", payload], cwd=tmp_package)
    assert r.returncode == 0, r.stdout
    html = (pkg_dir / "analysis.html").read_text()
    assert 'id="rule-no-mock"' in html and "Never paste metrics" in html
    assert "No rules recorded yet" not in html


def test_lesson_retire_repaints_placeholder_back(tmp_package):
    pkg_dir = tmp_package / "research_html" / "packages" / "test-pkg"
    (pkg_dir / "analysis.html").write_text(ANALYSIS)
    (pkg_dir / "results.html").write_text("<html><td>PASS</td></html>")
    payload = json.dumps({"level": "package", "pkg": "test-pkg", "kind": "lesson",
                          "slug": "no-mock", "title": "No mocked metrics",
                          "text": "Never paste metrics without an artifact.",
                          "rationale": "T5", "addedAt": "2026-06-11"})
    _run(["--pkg", "test-pkg", "--op", "insert", "--target", "rule", "--payload", payload],
         cwd=tmp_package)
    r = _run(["--pkg", "test-pkg", "--op", "update", "--target", "rule",
              "--payload", json.dumps({"id": "test-pkg#no-mock", "status": "RETIRED",
                                       "retireReason": "wrong generalization"})], cwd=tmp_package)
    assert r.returncode == 0, r.stdout
    html = (pkg_dir / "analysis.html").read_text()
    assert "No rules recorded yet" in html and 'id="rule-no-mock"' not in html
