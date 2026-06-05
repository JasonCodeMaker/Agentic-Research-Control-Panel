"""Composite events — atomic fan-out of one event to multiple ops.

Each entry in EVENTS maps an event name to a list of (op, target, payload_mapper)
tuples. The fanout function dispatches each sub-op in order; if any reject, the
whole event reports rejected (no rollback — the agent is expected to fix and retry
from the cursor).
"""


# Payload mappers — extract per-op fields from the composite-event payload.
# Each takes the event's full payload dict and returns the per-op payload dict.

def _ch_update_status(payload: dict) -> dict:
    return {"to": "NEXT_ACTION_READY"}


def _ch_update_open_runs(payload: dict) -> dict:
    return {"to": "none"}


def _ch_update_last_action(payload: dict) -> dict:
    return {"to": "chain done"}


def _ch_update_last_updated_tracker(payload: dict) -> dict:
    return {"page": "tracker.html"}


def _ch_update_last_updated_results(payload: dict) -> dict:
    return {"page": "results.html"}


def _cs_update_live_check(payload: dict) -> dict:
    # payload from caller: {"exp_id": "P1", "artifact": "...", "measured": "..."}
    return {"exp_id": payload["exp_id"], "run_state": "completed",
            "metrics": payload.get("measured", "unmeasured")}


def _cs_update_allocation(payload: dict) -> dict:
    return {"exp_id": payload["exp_id"], "status": "completed"}


def _cs_insert_result_gate(payload: dict) -> dict:
    return {"exp_id": payload["exp_id"], "validity": "ok", "baseline": "unmeasured",
            "plan_gate": "unmeasured", "observed_metric": payload.get("measured", "unmeasured"),
            "budget_use": "unmeasured", "seed_status": "unmeasured",
            "artifact_completeness": "ok", "verdict": "pass", "reason": "checkpoint saved"}


def _cs_update_verdict(payload: dict) -> dict:
    return {"exp_id": payload["exp_id"], "measured": payload.get("measured", ""),
            "to": "pass"}


def _cs_update_exp_status(payload: dict) -> dict:
    return {"id": payload["exp_id"], "to": "completed"}


def _cs_update_last_updated_tracker(payload: dict) -> dict:
    return {"page": "tracker.html"}


def _cs_update_last_updated_results(payload: dict) -> dict:
    return {"page": "results.html"}


# Event → list of (op, target, payload_mapper) tuples.
EVENTS = {
    "chain-done": [
        # Per-phase ops (results-block, results-verdict, experiments-status) require the caller
        # to invoke this event ONCE PER PHASE, with the phase id in payload. For an MVP, we
        # only fan out the package-wide updates here; per-phase fan-out is left to the caller
        # for the first iteration.
        ("update", "status",            _ch_update_status),
        ("update", "openRuns",          _ch_update_open_runs),
        ("update", "lastAction",        _ch_update_last_action),
        ("update", "last-updated-time", _ch_update_last_updated_tracker),
        ("update", "last-updated-time", _ch_update_last_updated_results),
    ],

    "checkpoint-saved": [
        # Per-exp fan-out. Payload: {"exp_id": "...", "artifact": "...", "measured": "..."}.
        ("update", "tracker-live-check-row",          _cs_update_live_check),
        ("update", "tracker-resource-allocation-row", _cs_update_allocation),
        ("insert", "results-gate-row",                _cs_insert_result_gate),
        ("update", "results-verdict",                 _cs_update_verdict),
        ("update", "experiments-status",              _cs_update_exp_status),
        ("update", "last-updated-time",               _cs_update_last_updated_tracker),
        ("update", "last-updated-time",               _cs_update_last_updated_results),
    ],

    # sentinel-write, phase-marker, candidate-json: fan-outs deferred until concrete
    # surface map can be enumerated from a real running package (see Phase 6 pilot).
    "sentinel-write":  [],
    "phase-marker":    [],
    "candidate-json":  [],
}


def fanout(event: str, pkg: str, payload: dict, dispatch_fn) -> tuple[str, list[str]]:
    """Run every sub-op for `event`. If any rejects, abort and return ('rejected', files_touched_so_far).

    Note: true atomicity requires snapshot-and-rollback. For MVP we accept "stop on first
    reject and surface reject; the agent retries from cursor."
    """
    spec = EVENTS.get(event)
    if spec is None:
        raise SystemExit(f"unknown composite event: {event}")
    files: list[str] = []
    for op, target, mapper in spec:
        sub_payload = mapper(payload) if mapper else payload
        validation, sub_files = dispatch_fn(op, pkg, target, sub_payload)
        files.extend(sub_files)
        if validation != "passed":
            return "rejected", files
    return "passed", files
