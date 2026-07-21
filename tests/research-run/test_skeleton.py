"""L1 Experiment fixture composed through canonical state and run storage."""

from __future__ import annotations

import sys
from pathlib import Path

from lib.research_state import StateQuery

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-run" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import skeleton  # noqa: E402
from state_fixtures import CANONICAL_EXPERIMENT_ID, seed  # noqa: E402


INTENT = "measure the toy metric"


def _citations(tmp_path, *, include_missing=False):
    source = tmp_path / "source.txt"
    source.write_text("grounded source", encoding="utf-8")
    citations = [{"id": "real", "source": str(source)}]
    if include_missing:
        citations.append({"id": "missing", "source": str(tmp_path / "missing.txt")})
    return citations


def test_walking_skeleton_returns_commands_without_mutating_state(tmp_path):
    paths = seed(tmp_path)
    before = StateQuery(paths).show("experiment")
    result = skeleton.run(
        INTENT,
        pkg_id="pkg-1",
        workspace=paths,
        experiment_id="P1",
        citations=_citations(tmp_path),
        measured=0.9,
    )
    after = StateQuery(paths).show("experiment")
    assert result["chain"] == ["R2:search", "R4:experiment", "R5:verify"]
    assert result["experiment_id"] == CANONICAL_EXPERIMENT_ID
    assert result["verdict"]["result"] == "PASS"
    assert len(result["required_mutations"]) == 2
    assert len(result["research_op_commands"]) == 2
    assert after["source_seq"] == before["source_seq"]
    assert after["source_hash"] == before["source_hash"]


def test_missing_citation_is_rejected_but_grounded_source_survives(tmp_path):
    paths = seed(tmp_path)
    result = skeleton.run(
        INTENT,
        pkg_id="pkg-1",
        workspace=paths,
        experiment_id="P1",
        citations=_citations(tmp_path, include_missing=True),
        measured=0.9,
    )
    assert result["verified_citations"] == ["real"]
    assert result["rejected_citations"] == ["missing"]


def test_gate_miss_emits_failed_result_and_experiment_status(tmp_path):
    paths = seed(tmp_path)
    result = skeleton.run(
        INTENT,
        pkg_id="pkg-1",
        workspace=paths,
        experiment_id="P1",
        citations=[],
        measured=0.5,
    )
    assert result["verdict"]["result"] == "FAIL"
    result_row, status = result["required_mutations"]
    assert result_row["payload"]["validity"] == "RESULT_FAIL"
    assert status["payload"]["to"] == "FAILED"
    assert result["run"]["status"]["status"] == "COMPLETED"
