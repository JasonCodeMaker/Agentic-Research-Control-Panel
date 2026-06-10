"""Stage-0 verifier hook: acquitting (crossing into the success lane) requires a verdict record."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))
import validate  # noqa: E402

CLI = ROOT / "skills" / "research-op" / "scripts" / "research_op.py"
_IN_PROGRESS = {"category": "in-progress", "status": "CONTEXT_LOADED"}


def _acquit_payload(with_verdict):
    p = {
        "to_status": "ADOPTED_UNCONFIRMED",
        "to_category": "success",
        "ack_token": "user-ack-123",
        "terminationMessage": "beat baseline by 3pts",
        "adoptionPath": "CLAUDE.md#current-best",
    }
    if with_verdict:
        p["verdict"] = {"judge": "claude-sonnet-4-6", "verdict": "SOUND",
                        "evidence": "beat baseline by 3pts"}
    return p


def test_acquit_without_verdict_rejected():
    rej = validate.validate("test-pkg", "update", "status", _acquit_payload(False), _IN_PROGRESS)
    assert rej is not None and rej.rule == "acquit-needs-verdict"


def test_acquit_with_verdict_passes():
    rej = validate.validate("test-pkg", "update", "status", _acquit_payload(True), _IN_PROGRESS)
    assert rej is None


def test_non_acquit_status_update_not_gated():
    rej = validate.validate("test-pkg", "update", "status", {"to_status": "IMPLEMENTING"}, _IN_PROGRESS)
    assert rej is None


def _run(args, cwd):
    return subprocess.run([sys.executable, str(CLI), *args], cwd=cwd,
                          capture_output=True, text=True)


def test_acquit_without_verdict_rejected_via_cli(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "update", "--target", "status",
              "--payload", json.dumps(_acquit_payload(False))], cwd=tmp_package)
    assert r.returncode == 2
    env = json.loads(r.stdout)
    assert env["rejected"] is True
    assert env["rule"] == "acquit-needs-verdict"
