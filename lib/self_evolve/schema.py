"""Typed schema validators + content digests for the self-evolve Rule Store (v1).

Pure and node-free. Enforces the load-bearing invariants from plan §9.2-§9.4 / §10.1 /
§11.4: every entity declares a stable schema_version, scope and risk are bounded, and
every immutable record carries a deterministic SHA-256 content digest.
"""

import hashlib
import json

RULE_SCHEMA = "selfevolve.rule.v1"
SKILL_SCHEMA = "selfevolve.skill.v1"
TRANSITION_SCHEMA = "selfevolve.transition.v1"
EVENT_SCHEMA = "selfevolve.event.v1"
EVIDENCE_SCHEMA = "selfevolve.evidence.v1"
APPROVAL_SCHEMA = "selfevolve.approval.v1"

APPROVAL_OPERATIONS = ("install", "restore", "rollback")
APPROVAL_DECISIONS = ("approved", "rejected")

RISK_CLASSES = ("R0-observe", "R1-context", "R2-shadow", "R3-project-exec", "R4-trust-boundary")
ORACLE_RESULTS = ("pass", "fail", "inconclusive", "error")
STORES = ("rule", "skill")


class SchemaViolation(Exception):
    """Raised when a record breaks a schema invariant (reject-before-write)."""


def canonical(obj):
    """Deterministic JSON for digesting/serialization (sorted keys, compact)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_digest(obj, *, exclude=("content_digest",)):
    """SHA-256 over the record minus its own digest field(s); stable across key order."""
    payload = {k: v for k, v in obj.items() if k not in exclude}
    return "sha256:" + hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def _require(obj, fields, what):
    for f in fields:
        if f not in obj or obj[f] in (None, ""):
            raise SchemaViolation(f"{what}: missing required field {f!r}")


def _nonempty_list(obj, field, what):
    val = obj.get(field)
    if not isinstance(val, list) or not val:
        raise SchemaViolation(f"{what}: {field!r} must be a non-empty list")


def validate_scope(scope, what="rule"):
    """A scope is bounded only if it names a project and non-empty packages + task_types."""
    if not isinstance(scope, dict):
        raise SchemaViolation(f"{what}: scope must be an object")
    _require(scope, ("project",), f"{what}.scope")
    _nonempty_list(scope, "packages", f"{what}.scope")
    _nonempty_list(scope, "task_types", f"{what}.scope")


def validate_rule(rule):
    """Reject a Rule with a missing field, unbounded scope, illegal risk, or absent provenance."""
    if rule.get("schema_version") != RULE_SCHEMA:
        raise SchemaViolation(f"rule: schema_version must be {RULE_SCHEMA!r}")
    _require(rule, ("id", "version", "title", "description", "content", "risk_class"), "rule")
    if rule["risk_class"] not in RISK_CLASSES:
        raise SchemaViolation(f"rule: illegal risk_class {rule['risk_class']!r}")
    validate_scope(rule.get("scope"), "rule")
    prov = rule.get("provenance")
    if not isinstance(prov, dict) or not prov.get("generated_by"):
        raise SchemaViolation("rule: provenance.generated_by is required")
    policy = rule.get("validation_policy", {})
    _nonempty_list(policy, "required_oracles", "rule.validation_policy")
    return True


def validate_transition(t):
    """Reject a transition envelope missing concurrency, target, or identity fields."""
    if t.get("schema_version") != TRANSITION_SCHEMA:
        raise SchemaViolation(f"transition: schema_version must be {TRANSITION_SCHEMA!r}")
    _require(t, ("transition_id", "entity_id", "entity_version", "expected_from_state",
                "to_state", "op", "idempotency_key"), "transition")
    if t.get("store") not in STORES:
        raise SchemaViolation(f"transition: store must be one of {STORES}")
    if t.get("risk_class") not in RISK_CLASSES:
        raise SchemaViolation(f"transition: illegal risk_class {t.get('risk_class')!r}")
    return True


def validate_skill_manifest(m):
    """Reject a Skill manifest missing identity, bounded scope/permissions, tests, or rollback (§9.5)."""
    if m.get("schema_version") != SKILL_SCHEMA:
        raise SchemaViolation(f"skill: schema_version must be {SKILL_SCHEMA!r}")
    _require(m, ("id", "version", "kind", "description", "bundle_digest", "risk_class"), "skill")
    if m["risk_class"] not in RISK_CLASSES:
        raise SchemaViolation(f"skill: illegal risk_class {m['risk_class']!r}")
    scope = m.get("scope", {})
    if not isinstance(scope, dict):
        raise SchemaViolation("skill: scope must be an object")
    _nonempty_list(scope, "trigger_family", "skill.scope")
    perms = m.get("permissions")
    if not isinstance(perms, dict):
        raise SchemaViolation("skill: permissions must be an object")
    _nonempty_list(perms, "tools", "skill.permissions")
    tests = m.get("tests")
    if not isinstance(tests, dict) or not tests:
        raise SchemaViolation("skill: tests must be a non-empty object")
    if not isinstance(m.get("activation"), dict):
        raise SchemaViolation("skill: activation is required")
    if not isinstance(m.get("rollback"), dict):
        raise SchemaViolation("skill: rollback contract is required")
    prov = m.get("provenance")
    if not isinstance(prov, dict) or not prov.get("generated_by"):
        raise SchemaViolation("skill: provenance.generated_by is required")
    return True


def validate_approval(a):
    """Reject an approval not bound to an exact operation/version/digest triple (§9.6)."""
    if a.get("schema_version") != APPROVAL_SCHEMA:
        raise SchemaViolation(f"approval: schema_version must be {APPROVAL_SCHEMA!r}")
    _require(a, ("approval_id", "entity_type", "entity_id", "entity_version", "operation",
                "bundle_digest", "permission_digest", "evidence_digest", "decision",
                "approved_by", "approved_at"), "approval")
    if a["operation"] not in APPROVAL_OPERATIONS:
        raise SchemaViolation(f"approval: illegal operation {a['operation']!r}")
    if a["decision"] not in APPROVAL_DECISIONS:
        raise SchemaViolation(f"approval: illegal decision {a['decision']!r}")
    return True


def validate_event(e):
    """Reject an event missing type, idempotency, or observation time."""
    if e.get("schema_version") != EVENT_SCHEMA:
        raise SchemaViolation(f"event: schema_version must be {EVENT_SCHEMA!r}")
    _require(e, ("event_id", "type", "source", "idempotency_key", "observed_at"), "event")
    return True


def validate_evidence(ev):
    """Reject an evidence record without a legal oracle result."""
    if ev.get("schema_version") != EVIDENCE_SCHEMA:
        raise SchemaViolation(f"evidence: schema_version must be {EVIDENCE_SCHEMA!r}")
    _require(ev, ("evidence_id", "entity_id", "entity_version", "stage", "oracle"), "evidence")
    oracle = ev.get("oracle", {})
    if oracle.get("result") not in ORACLE_RESULTS:
        raise SchemaViolation(f"evidence: oracle.result must be one of {ORACLE_RESULTS}")
    return True
