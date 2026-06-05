"""Phase 3 — user-approved deployment, canary, suspend, rollback (§14 Phase 3)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

from ops import evolution  # noqa: E402
from self_evolve import bundle, install, schema, store  # noqa: E402


def _files(v="1.0.0"):
    return {"SKILL.md": f"# skill v{v}", "run.py": "print('ok')\n"}


def _manifest(version="1.0.0", **over):
    files = _files(version)
    base = {
        "schema_version": schema.SKILL_SCHEMA, "id": "skill.metric-check", "version": version,
        "kind": "project-claude-skill", "description": "metric check",
        "bundle_digest": bundle.bundle_digest(files),
        "scope": {"project_root": ".", "packages": ["*"], "trigger_family": ["metric-change"]},
        "permissions": {"tools": ["Read"], "read_roots": ["."],
                        "write_roots": ["${SELF_EVOLVE_ROOT}/sandboxes/<run-id>"],
                        "network": "deny", "credentials": "deny"},
        "inputs": [], "outputs": [], "invariants": ["x"],
        "tests": {"static": ["x"]}, "provenance": {"generated_by": "skill-inducer-v1"},
        "activation": {"initial_mode": "canary", "allowed_scope": ["metric-change"]},
        "rollback": {"suspend_on_oracle_fail": True}, "risk_class": "R3-project-exec",
    }
    base.update(over)
    return base


def _approval(manifest, operation="install", **over):
    base = {
        "schema_version": schema.APPROVAL_SCHEMA, "approval_id": f"apr_{operation}_{manifest['version']}",
        "entity_type": "skill", "entity_id": manifest["id"], "entity_version": manifest["version"],
        "operation": operation, "bundle_digest": manifest["bundle_digest"],
        "permission_digest": bundle.permission_digest(manifest["permissions"]),
        "evidence_digest": "sha256:ev", "decision": "approved", "approved_by": "user",
        "approved_at": "2026-06-05T00:00:00+10:00",
    }
    base.update(over)
    return base


def _drive_to_awaiting(se, version="1.0.0"):
    m = _manifest(version)
    evolution.run("evolution-create", {"manifest": m, "files": _files(version)}, se)
    for frm, to in [("candidate", "validating"), ("validating", "validated"),
                    ("validated", "awaiting_install_approval")]:
        evolution.run("evolution-transition",
                      {"schema_version": schema.TRANSITION_SCHEMA, "transition_id": f"t-{to}-{version}",
                       "store": "skill", "entity_id": m["id"], "entity_version": version,
                       "expected_from_state": frm, "to_state": to, "op": "advance",
                       "risk_class": "R3-project-exec", "idempotency_key": f"{m['id']}:{version}:{to}"}, se)
    return m


def test_validated_seals_release(tmp_path):
    se = tmp_path / "_selfevolve"
    _drive_to_awaiting(se)
    assert (se / "skills" / "releases" / "skill.metric-check" / "1.0.0" / "manifest.json").exists()


def test_install_with_valid_approval_reaches_canary(tmp_path):
    se, proj = tmp_path / "_selfevolve", tmp_path / "proj"
    m = _drive_to_awaiting(se)
    evolution.run("evolution-approve", _approval(m), se, proj)
    st, _, _ = evolution.run("evolution-install-skill",
                             {"entity_id": m["id"], "entity_version": "1.0.0",
                              "approval_id": "apr_install_1.0.0"}, se, proj)
    assert st == "passed"
    link = proj / ".claude" / "skills" / m["id"]
    assert link.is_symlink()
    assert store.current_state(store.read_log(se / "skills" / "transitions.jsonl"),
                               m["id"], "1.0.0") == "canary"


def test_install_rejects_mismatched_bundle_digest(tmp_path):
    se, proj = tmp_path / "_selfevolve", tmp_path / "proj"
    m = _drive_to_awaiting(se)
    bad = _approval(m, bundle_digest="sha256:wrong", approval_id="apr_bad")
    evolution.run("evolution-approve", bad, se, proj)
    with pytest.raises(evolution.EvolutionReject) as e:
        evolution.run("evolution-install-skill",
                      {"entity_id": m["id"], "entity_version": "1.0.0", "approval_id": "apr_bad"}, se, proj)
    assert e.value.rule == "approval-mismatch"
    # install_failed, no active pointer
    assert not (proj / ".claude" / "skills" / m["id"]).exists()


def test_install_rejects_expired_approval(tmp_path):
    se, proj = tmp_path / "_selfevolve", tmp_path / "proj"
    m = _drive_to_awaiting(se)
    exp = _approval(m, expires_at="2020-01-01T00:00:00+10:00", approval_id="apr_exp")
    evolution.run("evolution-approve", exp, se, proj)
    with pytest.raises(evolution.EvolutionReject):
        evolution.run("evolution-install-skill",
                      {"entity_id": m["id"], "entity_version": "1.0.0", "approval_id": "apr_exp",
                       "now": "2026-06-05T00:00:00+10:00"}, se, proj)


def test_worker_cannot_approve(tmp_path, monkeypatch):
    se, proj = tmp_path / "_selfevolve", tmp_path / "proj"
    m = _drive_to_awaiting(se)
    monkeypatch.setenv("RESEARCH_OP_AGENT", "self-evolve-worker")
    with pytest.raises(evolution.EvolutionReject) as e:
        evolution.run("evolution-approve", _approval(m), se, proj)
    assert e.value.rule == "worker-cannot-approve"


def test_canary_scope_enforcement():
    m = _manifest()
    assert install.is_invocation_allowed("canary", m, "metric-change")[0] is True
    ok, reason = install.is_invocation_allowed("canary", m, "delete-everything")
    assert ok is False and reason == "canary-scope-escape"


def test_suspended_denies_invocation():
    ok, reason = install.is_invocation_allowed("suspended", _manifest(), "metric-change")
    assert ok is False and reason == "suspended"


def test_suspend_then_deny(tmp_path):
    se, proj = tmp_path / "_selfevolve", tmp_path / "proj"
    m = _drive_to_awaiting(se)
    evolution.run("evolution-approve", _approval(m), se, proj)
    evolution.run("evolution-install-skill",
                  {"entity_id": m["id"], "entity_version": "1.0.0", "approval_id": "apr_install_1.0.0"}, se, proj)
    st, _, _ = evolution.run("evolution-suspend-skill",
                             {"entity_id": m["id"], "entity_version": "1.0.0", "reason": "regression"}, se, proj)
    assert st == "passed"
    assert store.current_state(store.read_log(se / "skills" / "transitions.jsonl"),
                               m["id"], "1.0.0") == "suspended"


def test_rollback_requires_authorization():
    ok, reason = install.authorize_rollback(target_version="1.0.0")
    assert ok is False and reason == "no-authorization"
    ok, _ = install.authorize_rollback(target_version="1.0.0",
                                       pre_authorization={"rollback_to": "1.0.0"})
    assert ok is True
    ok, reason = install.authorize_rollback(target_version="1.0.0",
                                            pre_authorization={"rollback_to": "9.9.9"})
    assert ok is False and reason == "pre-authorization-target-mismatch"
