"""Event → Rule candidate induction (plan §10.2). Pure: the LLM draft is injected.

`build_prompt` is the deterministic instruction contract the op handler hands to the LLM;
`induce_rule` assembles a schema-valid candidate from the event + the returned draft,
stamping provenance and the per-event validation profile. No generalization happens here —
correction-scope is enforced downstream by the correction_integrity oracle.
"""

from self_evolve import schema

# Per-trigger required-oracle profile (§11.2 / §10.2).
RULE_PROFILES = {
    "test-failure-fixed": ["schema_scope", "faithfulness", "original_reproduction",
                           "regression_smoke", "conflict"],
    "user-correction":    ["schema_scope", "correction_integrity", "conflict", "regression_smoke"],
    "workflow-repeated":  ["schema_scope", "faithfulness", "regression_smoke", "conflict"],
}


def build_prompt(event):
    """Deterministic induction instruction for the injected LLM judge/inducer."""
    etype = event.get("type")
    lines = [
        f"Induce one bounded Rule from this {etype} event.",
        f"Subject: {event.get('subject')}",
        "Return title, description, content (a strategy-level guardrail, not raw actions),",
        "and a bounded scope (project, packages, task_types).",
    ]
    if etype == "user-correction":
        lines.append("CRITICAL: capture only the exact correction; do NOT generalize beyond it.")
    return "\n".join(lines)


def classify_risk(draft):
    """Default advisory R1_CONTEXT unless the draft declares a default/trust-changing effect."""
    rc = draft.get("risk_class")
    if rc in schema.RISK_CLASSES:
        return rc
    return "R1_CONTEXT"


def induce_rule(event, draft, *, version="1.0.0"):
    """Assemble a schema-valid candidate Rule from an event + an LLM draft. Raises if incomplete."""
    etype = event.get("type")
    if etype not in RULE_PROFILES:
        raise schema.SchemaViolation(f"no Rule profile for event type {etype!r}")
    rule = {
        "schema_version": schema.RULE_SCHEMA,
        "id": draft["id"],
        "version": version,
        "title": draft["title"],
        "description": draft["description"],
        "content": draft["content"],
        "scope": draft["scope"],
        "trigger_signals": draft.get("trigger_signals", [etype]),
        "risk_class": classify_risk(draft),
        "provenance": {
            "generated_by": "rule-inducer-v1",
            "source_event_ids": [event["event_id"]],
            "source_trajectory_digests": draft.get("source_trajectory_digests", []),
        },
        "validation_policy": {"required_oracles": RULE_PROFILES[etype]},
        "supersedes": draft.get("supersedes", []),
    }
    rule["content_digest"] = schema.content_digest(rule)
    schema.validate_rule(rule)
    return rule
