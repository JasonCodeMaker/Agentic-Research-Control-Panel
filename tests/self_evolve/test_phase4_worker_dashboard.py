"""Dashboard projection for active self-evolution Rules."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

from ops import evolution  # noqa: E402
from self_evolve import dashboard, schema  # noqa: E402

def _seed_rule_active(se):
    evidence = {
        "uri": "experiments/pkg/exp/run/result.json",
        "sha256": "f" * 64,
        "size_bytes": 1,
        "kind": "FILE",
        "package_id": "pkg",
        "experiment_id": "pkg::exp",
        "run_id": "run",
    }
    rule = {"schema_version": schema.RULE_SCHEMA, "id": "rule.x", "version": "1.0.0",
            "title": "t", "description": "d", "content": "c",
            "scope": {"project": "*", "packages": ["*"], "task_types": ["x"]},
            "risk_class": "R1_CONTEXT", "provenance": {"generated_by": "g"},
            "validation_policy": {"required_oracles": ["faithfulness", "conflict"]},
            "evidence_refs": [evidence]}
    evolution.run("evolution-create", rule, se)
    for frm, to in [("CANDIDATE", "VALIDATING"), ("VALIDATING", "PROVISIONAL"),
                    ("PROVISIONAL", "RULE_ACTIVE")]:
        evolution.run("evolution-transition",
                      {"schema_version": schema.TRANSITION_SCHEMA, "transition_id": f"t-{to}",
                       "store": "rule", "entity_id": "rule.x", "entity_version": "1.0.0",
                       "expected_from_state": frm, "to_state": to, "op": "promote",
                       "risk_class": "R1_CONTEXT", "idempotency_key": f"rule.x:{to}",
                       "evidence_refs": [evidence],
                       **({"admission": "FULLY_ADMITTED"} if to == "RULE_ACTIVE" else {})}, se)


def test_projection_reflects_active_rule(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_active(se)
    proj = dashboard.build_projection(se)
    assert proj["rules"]["rule.x@1.0.0"] == "RULE_ACTIVE"
    assert proj["counts"]["active_rules"] == 1


def test_projection_reader_does_not_write_interface_files(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_active(se)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert dashboard.build_projection(se)["rules"]["rule.x@1.0.0"] == "RULE_ACTIVE"
    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert after == before
    assert not hasattr(dashboard, "write_projection")


def test_consistency_fails_closed_on_drift(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_active(se)
    good = dashboard.build_projection(se)
    assert dashboard.assert_consistent(se, good) is True
    tampered = json.loads(json.dumps(good))
    tampered["rules"]["rule.x@1.0.0"] = "INVALIDATED"  # planted drift
    with pytest.raises(dashboard.ConsistencyError):
        dashboard.assert_consistent(se, tampered)
