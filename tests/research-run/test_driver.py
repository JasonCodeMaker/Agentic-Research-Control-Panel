"""Stage-0 production-loop contract: the agent-driven dispatch seam, testable with fake role adapters.

The driver runs role adapters in order, validates each typed role return, and collects the proposed
research-op mutation envelopes + a PACK candidate — without ever touching a package HTML surface.
Real sub-agent dispatch slots into the same seam in later stages.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "research-run" / "scripts"))
import driver  # noqa: E402

NODE = {
    "id": "dir/2026-driver", "level": "direction", "parents": ["project/main"],
    "version": 1, "status": "ACTIVE",
    "yardstick": {"hypothesis": "X improves recall", "metric": {"name": "recall", "dir": "higher"},
                  "baselines": ["b0"], "success_predicate": "measured >= 0.80"},
    "provenance": "txn-0",
}


def _ok_return(role, *, mutations=None):
    return {
        "agent_role": role, "assigned_scope": "dir/2026-driver", "status": "ROLE_OK",
        "evidence": [f"{role}-evidence"], "blockers": [],
        "recommended_next_action": "proceed", "mutations": mutations or [],
    }


def _adapter(ret):
    return lambda ctx: ret


# ---- role-return schema ----

def test_role_return_missing_evidence_rejected():
    ret = _ok_return("lit")
    ret["evidence"] = []
    errs = driver.validate_role_return(ret)
    assert any("evidence" in e for e in errs)


def test_role_return_missing_field_rejected():
    ret = _ok_return("lit")
    del ret["recommended_next_action"]
    errs = driver.validate_role_return(ret)
    assert any("recommended_next_action" in e for e in errs)


def test_role_return_blocked_requires_blockers():
    ret = _ok_return("run")
    ret["status"] = "ROLE_BLOCKED"
    ret["blockers"] = []
    errs = driver.validate_role_return(ret)
    assert any("blocker" in e for e in errs)


def test_valid_role_return_passes():
    assert driver.validate_role_return(_ok_return("scope")) == []


# ---- mutation envelope routing ----

def test_direct_file_write_refused():
    # a role that tries to write a file directly (not via a research-op surface) is rejected
    env = {"op": "write_file", "target": "research_html/packages/x/results.html",
           "payload": {"html": "<p>hi</p>"}}
    errs = driver.validate_mutation(env)
    assert errs  # both op and target are illegal


def test_unknown_target_refused():
    env = {"op": "insert", "target": "results.html", "payload": {}}
    errs = driver.validate_mutation(env)
    assert any("target" in e for e in errs)


def test_well_formed_envelope_passes():
    env = {"op": "insert", "target": "results-gate-row", "payload": {"exp_id": "e1"}}
    assert driver.validate_mutation(env) == []


# ---- the dispatch tick ----

def test_tick_collects_mutations_and_pack_candidate():
    muts = [{"op": "insert", "target": "results-gate-row", "payload": {"exp_id": "e1"}}]
    adapters = {
        "scope": _adapter(_ok_return("scope")),
        "verify": _adapter(_ok_return("verify", mutations=muts)),
    }
    result = driver.run_tick("2026-driver", NODE, ["scope", "verify"], adapters)
    assert result["rejection"] is None
    assert result["roles_run"] == ["scope", "verify"]
    assert muts[0] in result["proposed_mutations"]
    # PACK candidate is complete (no blank field) so an absent reader never sees a gap
    assert driver.pack.missing_fields(result["pack_candidate"]) == []


def test_tick_stops_on_invalid_return():
    bad = _ok_return("lit")
    bad["evidence"] = []
    adapters = {
        "scope": _adapter(_ok_return("scope")),
        "lit": _adapter(bad),
        "ideate": _adapter(_ok_return("ideate")),
    }
    result = driver.run_tick("2026-driver", NODE, ["scope", "lit", "ideate"], adapters)
    assert result["rejection"] is not None
    assert result["rejection"]["role"] == "lit"
    assert "ideate" not in result["roles_run"]   # dispatch halts at the rejected role
    assert result["proposed_mutations"] == []    # nothing from the rejected tick is emitted


def test_tick_refuses_role_mutation_to_raw_file():
    bad_mut = [{"op": "write_file", "target": "outputs/x/run.json", "payload": {}}]
    adapters = {"verify": _adapter(_ok_return("verify", mutations=bad_mut))}
    result = driver.run_tick("2026-driver", NODE, ["verify"], adapters)
    assert result["rejection"] is not None
    assert result["rejection"]["role"] == "verify"
