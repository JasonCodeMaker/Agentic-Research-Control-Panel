"""Persisted-verdict gate for lib/ranking — selection + audit record round-trip."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import ranking  # noqa: E402


def test_select_top_k_truncates():
    assert ranking.select_top_k(["a", "b", "c"], 2) == ["a", "b"]


def test_select_top_k_k_larger_than_list():
    assert ranking.select_top_k(["a"], 3) == ["a"]


def _record(producer="gen:ideate", judge="ranker"):
    return {
        "producer": producer,
        "judge": judge,
        "scope_version": 1,
        "candidate_set_id": "ideate/candidates.json",
        "candidate_set": ["hyp-001", "hyp-002", "hyp-003"],
        "ranking": ["hyp-002", "hyp-001"],
        "selected": ["hyp-002"],
        "rationale": {"hyp-002": "stronger signal"},
    }


def test_write_then_read_round_trip(tmp_path):
    rec = ranking.write_ranking_verdict(tmp_path, _record())
    assert rec["ranking_id"]
    again = ranking.read_ranking_verdict(tmp_path, rec["ranking_id"])
    assert again["selected"] == ["hyp-002"]
    assert again["judge"] == "ranker"


def test_write_rejects_self_judged(tmp_path):
    with pytest.raises(ranking.RankingError):
        ranking.write_ranking_verdict(tmp_path, _record(producer="ranker", judge="ranker"))


def test_write_rejects_missing_field(tmp_path):
    rec = _record()
    del rec["selected"]
    with pytest.raises(ranking.RankingError):
        ranking.write_ranking_verdict(tmp_path, rec)


def test_write_rejects_empty_selected(tmp_path):
    rec = _record()
    rec["selected"] = []
    with pytest.raises(ranking.RankingError):
        ranking.write_ranking_verdict(tmp_path, rec)


def test_write_allows_scope_version_zero(tmp_path):
    rec = _record()
    rec["scope_version"] = 0
    out = ranking.write_ranking_verdict(tmp_path, rec)
    assert out["scope_version"] == 0


# --- Gap 2: write re-validates internal consistency, not just field presence ---


def test_write_rejects_ranking_outside_candidate_set(tmp_path):
    rec = _record()
    rec["ranking"] = ["hyp-002", "hyp-999"]  # hyp-999 is not in candidate_set
    with pytest.raises(ranking.RankingError):
        ranking.write_ranking_verdict(tmp_path, rec)


def test_write_rejects_selected_not_in_ranking(tmp_path):
    rec = _record()
    rec["selected"] = ["hyp-003"]  # not present in ranking
    with pytest.raises(ranking.RankingError):
        ranking.write_ranking_verdict(tmp_path, rec)


def test_write_rejects_duplicate_ranking(tmp_path):
    rec = _record()
    rec["ranking"] = ["hyp-002", "hyp-002"]
    with pytest.raises(ranking.RankingError):
        ranking.write_ranking_verdict(tmp_path, rec)
