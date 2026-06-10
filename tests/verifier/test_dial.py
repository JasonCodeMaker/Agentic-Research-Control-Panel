"""Stage-2c: each autonomy-dial row is enforced (pause cadence + verifier independence)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import verifier  # noqa: E402


def test_supervised_pauses_at_every_gate():
    assert verifier.pauses_at("SUPERVISED", "TERMINAL") is True
    assert verifier.pauses_at("SUPERVISED", "INTERMEDIATE") is True


def test_checkpoints_pauses_only_at_terminal_gates():
    assert verifier.pauses_at("CHECKPOINTED", "TERMINAL") is True
    assert verifier.pauses_at("CHECKPOINTED", "INTERMEDIATE") is False


def test_async_never_blocks():
    assert verifier.blocks("DEFERRED") is False
    assert verifier.pauses_at("DEFERRED", "TERMINAL") is False


def test_autonomous_requires_cross_family_judge():
    assert verifier.INDEPENDENCE_TABLE["AUTONOMOUS"] == "CROSS_FAMILY"
    assert verifier.blocks("AUTONOMOUS") is False
