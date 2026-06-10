"""Launch acquit gate: entering READY_TO_LAUNCH from any status needs a distinct, acquitting verdict."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))
import validate  # noqa: E402

_IN_REVIEW = {"category": "in-progress", "status": "IMPLEMENTATION_REVIEW"}
_IMPLEMENTING = {"category": "in-progress", "status": "IMPLEMENTING"}


def _launch_payload(verdict=None):
    p = {"to_status": "READY_TO_LAUNCH"}
    if verdict is not None:
        p["reviewer_verdict"] = verdict
    return p


def _v(producer="impl:coder", judge="reviewer", result="SOUND"):
    return {"producer": producer, "judge": judge, "result": result,
            "scope_version": 1, "artifact_id": "diff-1"}


def test_launch_without_reviewer_verdict_rejected():
    rej = validate.validate("test-pkg", "update", "status", _launch_payload(), _IN_REVIEW)
    assert rej is not None and rej.rule == "launch-needs-verdict"


def test_launch_with_distinct_sound_verdict_passes():
    # Same-family but distinct roles + sound => passes (cross-family not hard-required here).
    rej = validate.validate("test-pkg", "update", "status", _launch_payload(_v()), _IN_REVIEW)
    assert rej is None


def test_launch_with_self_judged_verdict_rejected():
    rej = validate.validate("test-pkg", "update", "status",
                            _launch_payload(_v(producer="reviewer", judge="reviewer")), _IN_REVIEW)
    assert rej is not None and rej.rule == "launch-acquits"


def test_launch_with_non_acquitting_verdict_rejected():
    rej = validate.validate("test-pkg", "update", "status",
                            _launch_payload(_v(result="NEEDS_REVISION")), _IN_REVIEW)
    assert rej is not None and rej.rule == "launch-acquits"


def test_launch_from_implementing_also_gated():
    # Gap 3: the bypass path IMPLEMENTING -> READY_TO_LAUNCH is now gated too.
    rej = validate.validate("test-pkg", "update", "status", _launch_payload(), _IMPLEMENTING)
    assert rej is not None and rej.rule == "launch-needs-verdict"


def test_non_launch_transition_not_gated():
    # Moving to a non-launch status carries no reviewer requirement.
    rej = validate.validate("test-pkg", "update", "status",
                            {"to_status": "IMPLEMENTING"}, _IN_REVIEW)
    assert rej is None


def test_supervised_does_not_relax():
    # Gap 4: even with autonomy_level=SUPERVISED, a non-acquitting verdict is still rejected.
    payload = _launch_payload(_v(result="NEEDS_REVISION"))
    payload["autonomy_level"] = "SUPERVISED"
    rej = validate.validate("test-pkg", "update", "status", payload, _IN_REVIEW)
    assert rej is not None and rej.rule == "launch-acquits"


def test_launch_with_missing_judge_rejected():
    # The missing-identity branch (judge absent) is still a launch-acquits rejection.
    verdict = {"producer": "impl:coder", "result": "SOUND",
               "scope_version": 1, "artifact_id": "diff-1"}
    rej = validate.validate("test-pkg", "update", "status", _launch_payload(verdict), _IN_REVIEW)
    assert rej is not None and rej.rule == "launch-acquits"


def test_launch_autonomous_not_tightened():
    # Autonomy-independent both ways: at AUTONOMOUS, a distinct same-family sound verdict still passes
    # (this gate adds no cross-family requirement).
    payload = _launch_payload(_v())
    payload["autonomy_level"] = "AUTONOMOUS"
    rej = validate.validate("test-pkg", "update", "status", payload, _IN_REVIEW)
    assert rej is None
