import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts" / "learning_context_gate.py"


def _write_dashboard(root: Path) -> Path:
    rh = root / "research_html"
    data = rh / "data"
    data.mkdir(parents=True)
    (data / "schema.js").write_text("window.RESEARCH_STATUS_SCHEMA = {};\n", encoding="utf-8")
    (data / "research-packages.js").write_text(
        """window.RESEARCH_PACKAGES = [
  { id: "old-fail", category: "fail", status: "ARCHIVED",
    methodsTried: [{ method: "bad idea", hypothesis: "h", gate: "g", measured: "m", verdict: "FAIL", evidencePath: "e" }] },
  { id: "old-win", category: "success", status: "ADOPTED", adoptionPath: "models/x.py",
    methodsTried: [{ method: "good idea", hypothesis: "h", gate: "g", measured: "m", verdict: "PASS", evidencePath: "e" }] }
];
""",
        encoding="utf-8",
    )
    (data / "rules.js").write_text(
        """window.RESEARCH_RULES = [
  { "id": "PRJ-rule", "level": "project", "kind": "constraint", "title": "Rule",
    "text": "Read prior failures before proposing new work.", "rationale": "avoid repeats",
    "source": "user", "origin": "user", "status": "ACTIVE", "addedAt": "2026-06-11" }
];
""",
        encoding="utf-8",
    )
    (data / "gaps.jsonl").write_text(
        json.dumps({"id": "G1", "summary": "missing baseline", "status": "open"}) + "\n",
        encoding="utf-8",
    )
    return rh


def test_learning_context_gate_summarizes_current_learning_sources(tmp_path):
    root = _write_dashboard(tmp_path)

    result = subprocess.run(
        [sys.executable, str(GATE), "--root", str(root), "--json"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["counts"]["active_rules"] == 1
    assert payload["counts"]["failed_methods"] == 1
    assert payload["counts"]["adopted_wins"] == 1
    assert payload["counts"]["open_gaps"] == 1
    assert payload["sources"]["packages"] == "loaded"
    assert payload["sources"]["rules"] == "loaded"


def test_learning_context_gate_fails_closed_on_malformed_rules(tmp_path):
    root = _write_dashboard(tmp_path)
    (root / "data" / "rules.js").write_text("window.BAD_RULES = [];\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(GATE), "--root", str(root), "--json"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "rules" in payload["errors"][0]

