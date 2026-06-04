"""Unit gate for lib/ranking — the deterministic ranking-jury guard (no model call)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import ranking  # noqa: E402


def test_rank_request_passes_paths_not_content():
    req = ranking.rank_request(
        ["hyp-001", "hyp-002"],
        ["outputs/pkg/ideate/candidates.json"],
        "Rank for a top-venue submission.",
        top_k=2,
    )
    assert req["candidate_ids"] == ["hyp-001", "hyp-002"]
    assert req["candidate_artifact_paths"] == ["outputs/pkg/ideate/candidates.json"]
    assert req["top_k"] == 2
    assert "instruction" in req  # only ids + paths handed over, never candidate content


def test_parse_ranking_accepts_clean_json():
    raw = '{"ranking": ["hyp-002", "hyp-001"], "rationale": {"hyp-002": "stronger signal"}}'
    out = ranking.parse_ranking(raw, ["hyp-001", "hyp-002"])
    assert out["ranking"] == ["hyp-002", "hyp-001"]
    assert out["rationale"]["hyp-002"] == "stronger signal"


def test_parse_ranking_tolerates_code_fence_and_prose():
    raw = 'Here is my ranking:\n```json\n{"ranking": ["hyp-001"]}\n```\n'
    out = ranking.parse_ranking(raw, ["hyp-001", "hyp-002"])
    assert out["ranking"] == ["hyp-001"]


def test_parse_ranking_rejects_unknown_id():
    with pytest.raises(ranking.RankingError):
        ranking.parse_ranking('{"ranking": ["hyp-999"]}', ["hyp-001", "hyp-002"])


def test_parse_ranking_rejects_unparseable():
    with pytest.raises(ranking.RankingError):
        ranking.parse_ranking("no json here", ["hyp-001"])


def test_parse_ranking_rejects_empty_ranking():
    with pytest.raises(ranking.RankingError):
        ranking.parse_ranking('{"ranking": []}', ["hyp-001"])


def _ids():
    return ["hyp-001", "hyp-002", "hyp-003"]


def test_distinct_roles_same_model_passes():
    # Two Claude sub-agents are independent enough for a ranking — distinct ROLE ids.
    assert ranking.assess_ranking(
        ["hyp-001"], _ids(), producer="gen:lens-scaling", judge="ranker") is None


def test_producer_equals_judge_rejected():
    assert ranking.assess_ranking(
        ["hyp-001"], _ids(), producer="ranker", judge="ranker") is not None


def test_missing_identity_rejected():
    assert ranking.assess_ranking(["hyp-001"], _ids(), producer="", judge="ranker") is not None


def test_fabricated_id_rejected():
    assert ranking.assess_ranking(
        ["hyp-999"], _ids(), producer="gen", judge="ranker") is not None


def test_duplicate_ranking_rejected():
    assert ranking.assess_ranking(
        ["hyp-001", "hyp-001"], _ids(), producer="gen", judge="ranker") is not None


def test_empty_ranking_rejected():
    assert ranking.assess_ranking([], _ids(), producer="gen", judge="ranker") is not None


def test_ranking_longer_than_candidates_rejected():
    assert ranking.assess_ranking(
        ["hyp-001", "hyp-002", "hyp-003", "hyp-004"], _ids(),
        producer="gen", judge="ranker") is not None
