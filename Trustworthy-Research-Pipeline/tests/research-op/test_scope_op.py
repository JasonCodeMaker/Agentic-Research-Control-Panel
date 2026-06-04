"""CLI integration: the scope-transition op routes the SSOT writer through research-op."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "skills" / "research-op" / "scripts" / "research_op.py"


def _run(args, cwd):
    return subprocess.run([sys.executable, str(CLI), *args], cwd=cwd,
                          capture_output=True, text=True)


def _direction_payload(gate):
    return {
        "id": "dir/test-pkg", "level": "direction", "parents": ["project/main"],
        "version": 1, "status": "active",
        "yardstick": {
            "hypothesis": "h", "metric": {"name": "nDCG@10", "dir": "higher"},
            "baselines": ["xpool"], "success_predicate": "nDCG@10 >= base + 2",
        },
        "provenance": "txn-0",
        "op": "revise", "gate": gate, "trigger": "exp#42", "cause": "metric saturated",
    }


def test_scope_transition_legal_writes_log_and_audit(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "scope-transition",
              "--payload", json.dumps(_direction_payload("user+xmodel-audit"))],
             cwd=tmp_package)
    assert r.returncode == 0, r.stdout + r.stderr
    log = tmp_package / "var" / "research" / "_scope" / "transitions.jsonl"
    recs = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert len(recs) == 1
    assert recs[0]["node_id"] == "dir/test-pkg"
    assert recs[0]["op"] == "revise"
    audit = (tmp_package / "var" / "research" / "test-pkg" / "_actions.jsonl").read_text()
    assert '"validation": "passed"' in audit


def test_scope_transition_illegal_gate_rejected(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "scope-transition",
              "--payload", json.dumps(_direction_payload("agent+async-ack"))],
             cwd=tmp_package)
    assert r.returncode == 2
    env = json.loads(r.stdout)
    assert env["rejected"] is True
    assert env["phase"] == "scope-gate"
    log = tmp_package / "var" / "research" / "_scope" / "transitions.jsonl"
    assert (not log.exists()) or log.read_text().strip() == ""  # reject-before-write
    audit = (tmp_package / "var" / "research" / "test-pkg" / "_actions.jsonl").read_text()
    assert '"validation": "rejected"' in audit
