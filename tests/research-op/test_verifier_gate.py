"""Stage-2a gate: the acquit gate enforces L2 independence (producer != judge, cross-family for Autonomous)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts"))
import validate  # noqa: E402

_IN_PROGRESS = {"category": "in-progress", "status": "RESULT_ANALYSIS"}


def _acquit(level, producer, judge, result="SOUND"):
    return {
        "to_status": "ADOPTED_UNCONFIRMED", "to_category": "success",
        "ack_token": "user-ack", "terminationMessage": "m", "adoptionPath": "CLAUDE.md#cb",
        "control_mode": level,
        "verdict": {"producer": producer, "judge": judge, "result": result, "evidence": "e"},
    }


def test_producer_equals_judge_rejected():
    rej = validate.validate("p", "update", "status",
                            _acquit("DEFERRED", "claude-opus-4-8", "claude-opus-4-8"), _IN_PROGRESS)
    assert rej is not None and rej.rule == "acquit-judge-independent"


def test_passes_l1_but_refuted_by_jury_blocked():
    rej = validate.validate("p", "update", "status",
                            _acquit("DEFERRED", "claude-opus-4-8", "gpt-5", result="UNSOUND"), _IN_PROGRESS)
    assert rej is not None and rej.rule == "acquit-judge-independent"


def test_autonomous_without_cross_family_judge_refuses():
    rej = validate.validate("p", "update", "status",
                            _acquit("AUTONOMOUS", "claude-opus-4-8", "claude-sonnet-4-6"), _IN_PROGRESS)
    assert rej is not None and rej.rule == "acquit-judge-independent"


def test_autonomous_with_cross_family_judge_passes():
    rej = validate.validate("p", "update", "status",
                            _acquit("AUTONOMOUS", "claude-opus-4-8", "gpt-5"), _IN_PROGRESS)
    assert rej is None
