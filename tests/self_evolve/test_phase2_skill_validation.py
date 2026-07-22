"""Phase 2 — Skill candidate generation + sandbox validation (§14 Phase 2)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

from ops import evolution  # noqa: E402
from self_evolve import bundle, sandbox, schema, skill_lifecycle, store  # noqa: E402


def _files():
    return {"SKILL.md": "# metric check\nrun the validator", "run.py": "print('ok')\n"}


def _manifest(**over):
    files = over.pop("_files", _files())
    base = {
        "schema_version": schema.SKILL_SCHEMA,
        "id": "skill.metric-contract-check", "version": "1.0.0",
        "kind": "project-claude-skill", "description": "metric-contract validation",
        "bundle_digest": bundle.bundle_digest(files),
        "scope": {"project_root": ".", "packages": ["*"], "trigger_family": ["metric-change"]},
        "permissions": {"tools": ["Read", "Bash(python3 *)"], "read_roots": ["."],
                        "write_roots": ["${SELF_EVOLVE_ROOT}/sandboxes/<run-id>"],
                        "network": "deny", "credentials": "deny"},
        "inputs": [], "outputs": [], "invariants": ["all writes via research-op"],
        "tests": {"static": ["x"], "replay": ["x"]},
        "provenance": {"generated_by": "skill-inducer-v1"},
        "activation": {"initial_mode": "canary", "allowed_scope": ["metric-change"]},
        "rollback": {"suspend_on_oracle_fail": True}, "risk_class": "R3_PROJECT_EXEC",
    }
    base.update(over)
    return base


# --- sandbox boundary (candidate cannot escape) ---

def test_sandbox_rejects_network():
    m = _manifest()
    m["permissions"]["network"] = "allow"
    assert "network-not-denied" in sandbox.permission_violations(m)


def test_sandbox_rejects_write_to_claude_skills():
    m = _manifest()
    m["permissions"]["write_roots"] = [".claude/skills/evil"]
    v = sandbox.permission_violations(m)
    assert any("forbidden-write" in x or "outside-sandbox" in x for x in v)


def test_sandbox_rejects_write_to_validators_and_stores():
    m = _manifest()
    m["permissions"]["write_roots"] = ["${SELF_EVOLVE_ROOT}/sandboxes/r/../rules/releases"]
    assert any("forbidden-write" in x for x in sandbox.permission_violations(m))


def test_sandbox_rejects_unbounded_tools():
    m = _manifest()
    m["permissions"]["tools"] = ["*"]
    assert "tools-unbounded" in sandbox.permission_violations(m)


def test_clean_manifest_is_sandbox_safe():
    assert sandbox.is_sandbox_safe(_manifest())


# --- skill lifecycle ---

def test_skill_lifecycle_happy_path_to_validated():
    for a, b in [("OBSERVED", "CANDIDATE"), ("CANDIDATE", "VALIDATING"),
                 ("VALIDATING", "VALIDATED"), ("VALIDATED", "AWAITING_INSTALL_APPROVAL")]:
        assert skill_lifecycle.validate_edge(a, b) is True


def test_skill_install_edge_requires_approval():
    assert skill_lifecycle.requires_approval("AWAITING_INSTALL_APPROVAL", "INSTALLING")
    assert skill_lifecycle.requires_approval("SUSPENDED", "CANARY")


def test_suspend_is_authority_removing():
    assert ("SKILL_ACTIVE", "SUSPENDED") in skill_lifecycle.AUTHORITY_REMOVING


# --- create-skill op ---

def test_create_skill_seals_candidate(tmp_path):
    st, files, _ = evolution.run("evolution-create",
                                 {"manifest": _manifest(), "files": _files()}, tmp_path)
    assert st == "PASSED"
    assert (tmp_path / "skills" / "candidates" / "skill.metric-contract-check"
            / "1.0.0" / "manifest.json").exists()
    assert store.current_state(store.read_log(tmp_path / "skills" / "transitions.jsonl"),
                               "skill.metric-contract-check", "1.0.0") == "CANDIDATE"


def test_create_skill_rejects_sandbox_violation(tmp_path):
    m = _manifest()
    m["permissions"]["network"] = "allow"
    with pytest.raises(evolution.EvolutionReject) as e:
        evolution.run("evolution-create", {"manifest": m, "files": _files()}, tmp_path)
    assert e.value.rule == "sandbox-violation"


def test_create_skill_rejects_bundle_mismatch(tmp_path):
    with pytest.raises(evolution.EvolutionReject) as e:
        evolution.run("evolution-create",
                      {"manifest": _manifest(), "files": {"SKILL.md": "tampered"}}, tmp_path)
    assert e.value.rule == "bundle-mismatch"


def test_skill_install_edge_blocked_in_plain_transition(tmp_path):
    # AWAITING_INSTALL_APPROVAL -> INSTALLING must use the dedicated install op, not transition
    t = {"schema_version": schema.TRANSITION_SCHEMA, "transition_id": "t1", "store": "skill",
         "entity_id": "skill.x", "entity_version": "1.0.0",
         "expected_from_state": "AWAITING_INSTALL_APPROVAL", "to_state": "INSTALLING",
         "op": "install", "risk_class": "R3_PROJECT_EXEC", "idempotency_key": "k"}
    with pytest.raises(evolution.EvolutionReject) as e:
        evolution.run("evolution-transition", t, tmp_path)
    assert e.value.rule == "use-dedicated-op"
