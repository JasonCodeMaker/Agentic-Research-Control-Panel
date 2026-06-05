"""Item 3 TDD gate: the compact Scope summary (profile + cards) is a projection of the SSOT.

Ledger 1 hci-live-dashboard / §8 "Profile = projection of a versioned Project node". The profile is
derived from the Project node; each Direction/Task becomes a card whose status tracks the SSOT; a
hand-edited summary that diverges from the projection is flagged.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))
import scope_ssot  # noqa: E402
import render_inventory as ri  # noqa: E402
from scope_ssot import RuleViolation  # noqa: E402


def _project_node():
    return {
        "id": "project/main", "level": "project", "parents": [], "version": 1, "status": "active",
        "yardstick": {"north_star": "trustworthy auto-research",
                      "contribution_spine": "typed gates + SSOT", "non_goals": "multi-project"},
        "provenance": "txn-0",
    }


def _direction_node(version=1, status="active"):
    return {
        "id": "dir/contrastive-v2", "level": "direction", "parents": ["project/main"],
        "version": version, "status": status,
        "yardstick": {"hypothesis": "contrastive pretrain helps recall",
                      "metric": {"name": "Recall@10", "dir": "higher"},
                      "baselines": ["xpool"], "success_predicate": "Recall@10 >= baseline + 2"},
        "provenance": "txn-0",
    }


def _log(tmp_path):
    log = tmp_path / "_scope" / "transitions.jsonl"
    scope_ssot.propose_transition(_project_node(), op="create", gate="user",
                                  log_path=log, trigger="t0", cause="init project")
    scope_ssot.propose_transition(_direction_node(), op="create", gate="user+xmodel-audit",
                                  log_path=log, trigger="t1", cause="init direction")
    return log


def test_profile_projects_project_node(tmp_path):
    proj = scope_ssot.fold(scope_ssot.read_log(_log(tmp_path)))
    inv = ri.build_inventory(proj)
    assert inv["profile"]["north_star"] == "trustworthy auto-research"
    assert inv["profile"]["contribution_spine"] == "typed gates + SSOT"
    assert inv["profile"]["non_goals"] == "multi-project"


def test_card_status_matches_ssot_task_state(tmp_path):
    log = _log(tmp_path)
    # archive the direction via a gated transition; the card must follow the SSOT
    scope_ssot.propose_transition(_direction_node(version=2, status="archived"), op="archive",
                                  gate="user+xmodel-audit", log_path=log, trigger="t2",
                                  cause="superseded")
    inv = ri.build_inventory(scope_ssot.fold(scope_ssot.read_log(log)))
    card = next(c for c in inv["cards"] if c["id"] == "dir/contrastive-v2")
    assert card["status"] == "archived"


def test_manual_inventory_divergence_flagged(tmp_path):
    proj = scope_ssot.fold(scope_ssot.read_log(_log(tmp_path)))
    inv = ri.build_inventory(proj)
    inv["profile"]["north_star"] = "something the SSOT never said"  # planted drift
    with pytest.raises(RuleViolation):
        ri.assert_inventory_consistent(inv, proj)
