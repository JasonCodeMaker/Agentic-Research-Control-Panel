"""Stage-2a unit gate for lib/verifier — the layered independence rules (no model call)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import verifier  # noqa: E402


def test_family_of():
    assert verifier.family_of("claude-opus-4-8") == "anthropic"
    assert verifier.family_of("gpt-5") == "openai"
    assert verifier.family_of("codex") == "openai"
    assert verifier.family_of("gemini-2.5") == "google"


def _verdict(producer, judge, result="sound"):
    return {"producer": producer, "judge": judge, "result": result, "evidence": "e"}


def test_supervised_skips_l2():
    # At Supervised the human is the backstop — L2 independence is not required.
    assert verifier.assess_acquit(_verdict("x", "x", result="pass"), "supervised") is None


def test_producer_equals_judge_rejected_when_independence_required():
    assert verifier.assess_acquit(_verdict("claude-opus-4-8", "claude-opus-4-8"), "async") is not None


def test_non_acquitting_verdict_blocks():
    assert verifier.assess_acquit(
        _verdict("claude-opus-4-8", "gpt-5", result="unsound"), "async") is not None


def test_autonomous_requires_cross_family():
    # same family (both anthropic) -> blocked
    assert verifier.assess_acquit(
        _verdict("claude-opus-4-8", "claude-sonnet-4-6"), "autonomous") is not None
    # cross family -> ok
    assert verifier.assess_acquit(
        _verdict("claude-opus-4-8", "gpt-5"), "autonomous") is None


def test_checkpoints_different_model_ok():
    assert verifier.assess_acquit(
        _verdict("claude-opus-4-8", "claude-sonnet-4-6"), "checkpoints") is None
