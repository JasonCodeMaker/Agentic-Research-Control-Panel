"""Background-worker core (plan §10): trigger→job, idempotency, budget, retry.

Pure and deterministic — the actual daemon (systemd service + path/timer trigger) just calls
these. Keeping the decision logic here makes the worker testable without a process.
"""

from self_evolve import schema

# Trigger → (candidate store, job kind) (§10.2). In v1 most map to the Rule Store; the
# workflow-repeated trigger escalates to a Skill candidate only in this Tier-2 build.
TRIGGER_JOBS = {
    "repeated-validator-rejection": ("rule", "cluster-failures-propose-rule"),
    "test-failure-fixed": ("rule", "reproduce-and-propose-rule"),
    "user-correction": ("rule", "capture-correction-rule"),
    "workflow-repeated": ("skill", "induce-bounded-skill"),
    "run-completed": ("evidence", "update-and-monitor"),
    "run-failed": ("evidence", "update-and-monitor"),
    "scope-transition": ("transition", "revalidate-affected"),
    "runtime-regression": ("transition", "suspend-or-invalidate"),
}

# Retry policy by failure class (§10.5).
RETRY_POLICY = {
    "transient": {"retry": True, "terminal": "dead-letter"},
    "lease-loss": {"retry": True, "terminal": "resume-from-evidence"},
    "oracle-fail": {"retry": False, "terminal": "reject-or-suspend"},
    "oracle-inconclusive": {"retry": True, "terminal": "escalate-tier"},
    "schema-rejection": {"retry": False, "terminal": "dead-letter"},
    "install-fail": {"retry": True, "terminal": "install-failed-current-release"},
    "budget-exhaustion": {"retry": False, "terminal": "pause"},
}


class UnknownTrigger(Exception):
    """Raised when an event type has no registered job mapping."""


def map_trigger(event_type):
    """(candidate_store, job_kind) for an event type."""
    if event_type not in TRIGGER_JOBS:
        raise UnknownTrigger(event_type)
    store_kind, job = TRIGGER_JOBS[event_type]
    return {"store": store_kind, "job": job}


def job_for_event(event):
    """Deterministic job spec from an event; idempotency key derives from the event's."""
    mapping = map_trigger(event["type"])
    return {
        "job_id": f"job:{event['idempotency_key']}:{mapping['job']}",
        "store": mapping["store"], "job": mapping["job"],
        "idempotency_key": f"{event['idempotency_key']}:{mapping['job']}",
        "causation_id": event["event_id"],
    }


def dedupe_jobs(jobs):
    """At-least-once delivery: collapse jobs sharing an idempotency_key (first wins)."""
    seen, out = set(), []
    for j in jobs:
        if j["idempotency_key"] in seen:
            continue
        seen.add(j["idempotency_key"])
        out.append(j)
    return out


def classify_retry(failure_class):
    """Retry decision for a failure class (§10.5). Unknown classes are treated as transient."""
    return RETRY_POLICY.get(failure_class, RETRY_POLICY["transient"])


def would_exceed(limits, spent, requested):
    """True iff adding `requested` to `spent` breaches any limit dimension."""
    for k, cap in limits.items():
        if cap is None:
            continue
        if spent.get(k, 0) + requested.get(k, 0) > cap:
            return True
    return False


def reserve(limits, spent, requested, *, on_exhaustion="pause"):
    """Budget gate (§10.6). Returns (decision, result).

    decision ∈ {'reserved','paused'}. Exhaustion is never success/fail — it pauses and the
    stage result is ORACLE_INCONCLUSIVE.
    """
    if would_exceed(limits, spent, requested):
        return on_exhaustion, schema.ORACLE_RESULTS[2]  # ORACLE_INCONCLUSIVE
    new_spent = dict(spent)
    for k, v in requested.items():
        new_spent[k] = new_spent.get(k, 0) + v
    return "reserved", new_spent
