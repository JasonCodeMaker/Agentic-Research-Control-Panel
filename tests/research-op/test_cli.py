import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts" / "research_op.py"


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(CLI)] + args,
        cwd=cwd, capture_output=True, text=True,
    )


def test_check_passes_on_legal_state(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "check"], cwd=tmp_package)
    assert r.returncode == 0, r.stderr
    log = tmp_package / "var" / "research" / "test-pkg" / "_actions.jsonl"
    entry = json.loads(log.read_text().strip())
    assert entry["op"] == "check"
    assert entry["validation"] == "passed"


def test_state_gate_rejects_illegal_insert(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "methodsTried",
              "--payload", "{}"], cwd=tmp_package)
    assert r.returncode == 2
    envelope = json.loads(r.stdout)
    assert envelope["rejected"] is True
    assert envelope["phase"] == "state-gate"
    assert envelope["rule"] == "illegal-transition"
