"""Stage-2c: each autonomy-dial row is enforced (pause cadence + verifier independence)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import verifier  # noqa: E402


def test_supervised_pauses_at_every_gate():
    assert verifier.pauses_at("supervised", "terminal") is True
    assert verifier.pauses_at("supervised", "intermediate") is True


def test_checkpoints_pauses_only_at_terminal_gates():
    assert verifier.pauses_at("checkpoints", "terminal") is True
    assert verifier.pauses_at("checkpoints", "intermediate") is False


def test_async_never_blocks():
    assert verifier.blocks("async") is False
    assert verifier.pauses_at("async", "terminal") is False


def test_autonomous_requires_cross_family_judge():
    assert verifier.INDEPENDENCE_TABLE["autonomous"] == "different-family"
    assert verifier.blocks("autonomous") is False
