"""Item 2 TDD gate: the dashboard scope projection is fold(transitions), and drift is caught.

Ledger 1 hci-live-dashboard / Ledger 2 SSOT#3 surfaces-are-projections / Ledger 3 dashboard scope
projection. The render step is the only writer; the check step rejects any projection that does not
equal fold(transitions).
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))
import scope_ssot  # noqa: E402
import render_scope_projection as rsp  # noqa: E402
from scope_ssot import RuleViolation  # noqa: E402


def _direction_node(version=1, predicate="Recall@10 >= baseline + 2"):
    return {
        "id": "dir/contrastive-v2", "level": "direction", "parents": ["project/main"],
        "version": version, "status": "active",
        "yardstick": {
            "hypothesis": "contrastive pretrain helps recall",
            "metric": {"name": "Recall@10", "dir": "higher"},
            "baselines": ["xpool"], "success_predicate": predicate,
        },
        "provenance": "txn-0",
    }


def _transitions(tmp_path):
    log = tmp_path / "_scope" / "transitions.jsonl"
    scope_ssot.propose_transition(_direction_node(1), op="create", gate="user+xmodel-audit",
                                  log_path=log, trigger="t0", cause="init")
    scope_ssot.propose_transition(_direction_node(2, "Recall@10 >= baseline + 3"), op="revise",
                                  gate="user+xmodel-audit", log_path=log, trigger="exp#42",
                                  cause="sharpened")
    return log


def test_render_writes_projection_equal_to_fold(tmp_path):
    log = _transitions(tmp_path)
    proj_path = tmp_path / "data" / "scope-projection.json"
    rsp.render(log, proj_path)
    written = json.loads(proj_path.read_text(encoding="utf-8"))
    assert written == scope_ssot.fold(scope_ssot.read_log(log))
    assert written["dir/contrastive-v2"]["version"] == 2
    companion = (tmp_path / "data" / "scope-projection.js").read_text(encoding="utf-8")
    assert companion.startswith("window.RESEARCH_SCOPE_PROJECTION = {")
    assert "dir/contrastive-v2" in companion


def test_check_passes_on_freshly_rendered_projection(tmp_path):
    log = _transitions(tmp_path)
    proj_path = tmp_path / "data" / "scope-projection.json"
    rsp.render(log, proj_path)
    rsp.check(log, proj_path)  # must not raise


def test_check_detects_manual_projection_drift(tmp_path):
    log = _transitions(tmp_path)
    proj_path = tmp_path / "data" / "scope-projection.json"
    rsp.render(log, proj_path)
    tampered = json.loads(proj_path.read_text(encoding="utf-8"))
    tampered["dir/contrastive-v2"]["yardstick"]["success_predicate"] = "Recall@10 >= baseline + 0"
    proj_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(RuleViolation):
        rsp.check(log, proj_path)
