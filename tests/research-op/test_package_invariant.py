"""package-invariant target (Fix 3b): a user directive that adds a binding rule ("one notebook per
figure") needs a structured, audited home — the session-b07d0f85 turn-2 rule landed only in doc prose
with zero tracked ops. It appends to bindingRules[] in the registry and is audited like any op.
"""

import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts" / "research_op.py"


def _run(args, cwd):
    return subprocess.run([sys.executable, str(CLI)] + args, cwd=cwd, capture_output=True, text=True)


def test_insert_package_invariant_appends_and_audits(tmp_package):
    payload = json.dumps({"rule": "one notebook per figure",
                          "rationale": "reproducibility", "addedAt": "2026-06-09"})
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "package-invariant",
              "--payload", payload], cwd=tmp_package)
    assert r.returncode == 0, r.stderr
    inv = (tmp_package / "research_html" / "data" / "research-packages.js").read_text()
    assert "bindingRules" in inv and "one notebook per figure" in inv
    log = tmp_package / "outputs" / "test-pkg" / "_actions.jsonl"
    entries = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    assert any(e.get("target") == "package-invariant" and e["validation"] == "PASSED" for e in entries)


def test_package_invariant_requires_rule_text(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "package-invariant",
              "--payload", "{}"], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rejected"] is True
