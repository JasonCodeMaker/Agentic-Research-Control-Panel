"""Resource allocation — typed server registry + allocation ledger.

Structured memory of the user's predefined servers (the connection knowledge)
and an append-only allocate/link/release ledger that makes occupancy a fold,
not a recollection. Passive and stdlib-only: this library recommends and
records; it never launches work or drives a remote. See
plan/2026-06-12-resource-allocation.md.
"""

import re
import sys
import uuid
from pathlib import Path
from typing import Any

from lib.research_state.io import canonical_json
from lib.research_state.paths import ResearchPaths
from lib.research_state.query import resolve_bound_experiment
from lib.research_state.store import CommandRejected, EventStore

RESEARCH_OP_SCRIPTS = (
    Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts"
)
if str(RESEARCH_OP_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RESEARCH_OP_SCRIPTS))

import management as research_management

SERVER_KINDS = ("local", "ssh", "slurm")
SERVER_STATUS = frozenset({"ACTIVE", "DISABLED"})
CONTROL_PATHS = ("direct", "tmux")
DEFAULT_START_LATENCY = {"local": 0, "ssh": 1, "slurm": 2}

SERVER_FIELDS = frozenset({
    "name", "kind", "status", "control", "gpus", "slurm", "env",
    "tags", "skill", "start_latency", "notes",
})
GPU_BLOCK_FIELDS = frozenset({"type", "count", "mem_gb", "ids"})

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RuleViolation(Exception):
    """Raised when a server or ledger op breaks an invariant (reject-before-write)."""

    def __init__(
        self,
        detail: str,
        *,
        rule: str = "resource-input-invalid",
        audited: bool = False,
    ):
        self.detail = detail
        self.rule = rule
        self.audited = audited
        super().__init__(detail)


_RESOURCE_AUDIT_FIELDS = frozenset(
    {
        "alloc_id",
        "experiment_id",
        "experiment_local_id",
        "field_names",
        "gpu_count",
        "gpu_ids",
        "gpu_observation_count",
        "gpu_type",
        "job_id",
        "kind",
        "operation",
        "outcome",
        "package_id",
        "run_id",
        "server",
    }
)


def _safe_audit_value(value: Any) -> Any:
    """Keep resource rejection payloads bounded and free of command material."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:256]
    if isinstance(value, (list, tuple)):
        return [_safe_audit_value(item) for item in value[:64]]
    return {"type": type(value).__name__}


def audit_rejection(
    root,
    *,
    command: str,
    payload: dict[str, Any],
    error: RuleViolation,
    actor: dict[str, str] | None = None,
) -> None:
    """Record one pre-store rejection without raw input, secrets, or commands."""
    if error.audited:
        return
    summary = {
        key: _safe_audit_value(value)
        for key, value in payload.items()
        if key in _RESOURCE_AUDIT_FIELDS
    }
    principal = actor or {"type": "agent", "id": "resource-allocator"}
    safe_actor = {
        "type": str(principal.get("type") or "agent")[:64],
        "id": str(principal.get("id") or "resource-allocator")[:128],
    }
    research_management.record_rejected_attempt(
        research_paths(root),
        command_name=command,
        actor=safe_actor,
        payload=summary,
        rule=error.rule,
        detail=f"{command} rejected by {error.rule}",
        entry_skill="research-resource",
    )
    error.audited = True


def research_paths(root) -> ResearchPaths:
    if isinstance(root, ResearchPaths):
        return root
    resolved = Path(root).expanduser().resolve()
    return ResearchPaths(workspace=resolved.parent, root=resolved)


def resources_root(root) -> Path:
    """Ephemeral probe snapshot directory, outside persistent management state."""
    return research_paths(root).runtime / "resource_snapshots"


def _store(root) -> EventStore:
    store = EventStore(research_paths(root))
    store.initialize()
    return store


def validate_server(server):
    """Reject a server dict with unknown fields, bad enums, or an unusable control/gpu block."""
    if not isinstance(server, dict):
        raise RuleViolation("server must be a JSON object")
    try:
        canonical_json(server)
    except (TypeError, ValueError) as exc:
        raise RuleViolation("server must contain only JSON-compatible values") from exc
    unknown = set(server) - SERVER_FIELDS
    if unknown:
        raise RuleViolation(f"unknown server fields: {sorted(unknown)}")
    name = server.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise RuleViolation(f"server name must be a non-empty token, got {name!r}")
    if server.get("kind") not in SERVER_KINDS:
        raise RuleViolation(f"kind must be one of {SERVER_KINDS}, got {server.get('kind')!r}")
    if server.get("status", "ACTIVE") not in SERVER_STATUS:
        raise RuleViolation(f"status must be one of {sorted(SERVER_STATUS)}")
    control = server.get("control", {"path": "direct"})
    if not isinstance(control, dict) or control.get("path") not in CONTROL_PATHS:
        raise RuleViolation(f"control.path must be one of {CONTROL_PATHS}")
    if control.get("path") == "tmux" and not control.get("tmux_session"):
        raise RuleViolation("control.path=tmux requires control.tmux_session")
    gpus = server.get("gpus", [])
    if not isinstance(gpus, list):
        raise RuleViolation("gpus must be a list of GPU capacity blocks")
    ids_by_type: dict[str, set[str]] = {}
    for gpu in gpus:
        if not isinstance(gpu, dict) or not isinstance(gpu.get("type"), str) or not gpu["type"].strip():
            raise RuleViolation(f"gpu block needs a type: {gpu!r}")
        unknown_gpu_fields = set(gpu) - GPU_BLOCK_FIELDS
        if unknown_gpu_fields:
            raise RuleViolation(
                f"unknown gpu block fields: {sorted(unknown_gpu_fields)}"
            )
        count = gpu.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise RuleViolation(f"gpu block needs an integer count >= 1: {gpu!r}")
        mem_gb = gpu.get("mem_gb")
        if mem_gb is not None and (
            isinstance(mem_gb, bool)
            or not isinstance(mem_gb, (int, float))
            or mem_gb <= 0
        ):
            raise RuleViolation(f"gpu block mem_gb must be a number > 0: {gpu!r}")
        declared_ids = gpu.get("ids")
        if declared_ids is not None:
            if (
                not isinstance(declared_ids, list)
                or len(declared_ids) != count
                or any(
                    not isinstance(gpu_id, str) or not gpu_id.strip()
                    for gpu_id in declared_ids
                )
            ):
                raise RuleViolation(
                    "gpu block ids must contain exactly count non-empty strings"
                )
            normalized_ids = [gpu_id.strip() for gpu_id in declared_ids]
            if len(normalized_ids) != len(set(normalized_ids)):
                raise RuleViolation("gpu block ids must be unique")
            occupied = ids_by_type.setdefault(gpu["type"].strip(), set())
            overlap = occupied.intersection(normalized_ids)
            if overlap:
                raise RuleViolation(
                    f"gpu block ids overlap for type {gpu['type']!r}: "
                    f"{sorted(overlap)}"
                )
            occupied.update(normalized_ids)
    tags = server.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise RuleViolation("tags must be a list of strings")
    latency = server.get("start_latency")
    if latency is not None and (
        isinstance(latency, bool)
        or not isinstance(latency, int)
        or latency < 0
    ):
        raise RuleViolation("start_latency must be an integer >= 0")


def _normalize_server(server):
    out = {k: v for k, v in server.items() if v is not None}
    out.setdefault("status", "ACTIVE")
    out.setdefault("control", {"path": "direct"})
    out.setdefault("gpus", [])
    out["gpus"] = [
        {
            **gpu,
            "type": gpu["type"].strip(),
            **(
                {"ids": [gpu_id.strip() for gpu_id in gpu["ids"]]}
                if gpu.get("ids") is not None
                else {}
            ),
        }
        for gpu in out["gpus"]
    ]
    out.setdefault("tags", [])
    out.setdefault("start_latency", DEFAULT_START_LATENCY[out["kind"]])
    return out


def load_registry(root):
    store = _store(root)
    state = store.state()
    rows = state["aggregates"]["resource"]
    first_seq = {}
    for event in store.events():
        if event["aggregate_type"] == "resource":
            first_seq.setdefault(event["aggregate_id"], event["seq"])
    return [
        dict(rows[name])
        for name in sorted(rows, key=lambda key: first_seq.get(key, 10**18))
    ]


def _register_server(
    root,
    server,
    *,
    idempotency_key=None,
    actor=None,
):
    """Validate then commit one versioned Resource aggregate."""
    validate_server(server)
    normalized = _normalize_server(server)
    store = _store(root)
    state = store.state()
    key = f"resource/{normalized['name']}"
    expected = int(state["aggregate_versions"].get(key, 0))
    digest = uuid.uuid5(uuid.NAMESPACE_URL, canonical_json(normalized)).hex
    try:
        research_management.register_resource(
            store.paths,
            normalized["name"],
            normalized,
            expected_version=expected,
            actor=actor or {"type": "user", "id": "resource-cli"},
            idempotency_key=idempotency_key or f"resource-register:{normalized['name']}:{digest}",
        )
    except CommandRejected as exc:
        raise RuleViolation(
            exc.detail,
            rule=exc.rule,
            audited=exc.audited,
        ) from exc
    return normalized


def register_server(
    root,
    server,
    *,
    idempotency_key=None,
    actor=None,
):
    """Validate, audit rejection if needed, and commit one Resource."""
    summary = {
        "server": server.get("name") if isinstance(server, dict) else None,
        "kind": server.get("kind") if isinstance(server, dict) else None,
        "field_names": (
            sorted(str(key) for key in server)
            if isinstance(server, dict)
            else []
        ),
    }
    try:
        return _register_server(
            root,
            server,
            idempotency_key=idempotency_key,
            actor=actor,
        )
    except RuleViolation as exc:
        audit_rejection(
            root,
            command="resource-register",
            payload=summary,
            error=exc,
            actor=actor or {"type": "user", "id": "resource-cli"},
        )
        raise


def get_server(root, name):
    for server in load_registry(root):
        if server["name"] == name:
            return server
    raise RuleViolation(f"server not registered: {name!r}")


def _validate_allocation_link(state, alloc_id, patch):
    """Validate one run/job binding against the allocation's owned Experiment."""
    run_id = patch.get("run_id")
    job_id = patch.get("job_id")
    if run_id is not None and (
        not isinstance(run_id, str) or not run_id.strip()
    ):
        raise CommandRejected(
            "resource-run-id-invalid",
            "run_id must be a non-empty string",
        )
    if job_id is not None and (
        not isinstance(job_id, str) or not job_id.strip()
    ):
        raise CommandRejected(
            "resource-job-id-invalid",
            "job_id must be a non-empty string",
        )
    if run_id is None and job_id is None:
        raise CommandRejected(
            "resource-link-target-required",
            "allocation link requires a non-empty run_id or job_id",
        )

    allocation = state["aggregates"]["resource_allocation"].get(alloc_id)
    if not isinstance(allocation, dict) or allocation.get("status") != "OPEN":
        raise CommandRejected(
            "resource-allocation-open",
            f"allocation is missing or closed: {alloc_id}",
        )
    package_id = allocation.get("package_id") or allocation.get("pkg")
    requested_experiment = (
        allocation.get("experiment_id") or allocation.get("exp_id")
    )
    if not isinstance(package_id, str) or not package_id:
        raise CommandRejected(
            "resource-package-missing",
            f"allocation {alloc_id} has no package identity",
        )
    if not isinstance(requested_experiment, str) or not requested_experiment:
        raise CommandRejected(
            "resource-experiment-missing",
            f"allocation {alloc_id} has no Experiment identity",
        )
    try:
        experiment_id, _ = resolve_bound_experiment(
            state["aggregates"]["experiment"],
            package_id,
            requested_experiment,
        )
    except ValueError as exc:
        raise CommandRejected("resource-experiment-invalid", str(exc)) from exc

    linked_run = allocation.get("run_id")
    if run_id is not None:
        if linked_run not in {None, "", run_id}:
            raise CommandRejected(
                "resource-allocation-bound",
                f"allocation {alloc_id} is already linked to {linked_run}",
            )
        run = state["aggregates"]["run"].get(run_id)
        if not isinstance(run, dict):
            raise CommandRejected(
                "authorized-run-required",
                f"allocation link requires an existing authorized run: {run_id}",
            )
        if run.get("status") not in {"QUEUED", "RUNNING", "STALE"}:
            raise CommandRejected(
                "resource-run-not-active",
                f"allocation link requires an open run, got {run.get('status')!r}",
            )
        if run.get("package_id") != package_id:
            raise CommandRejected(
                "resource-package-mismatch",
                f"run {run_id} belongs to another package",
            )
        if run.get("experiment_id") != experiment_id:
            raise CommandRejected(
                "resource-experiment-mismatch",
                f"run {run_id} belongs to another Experiment",
            )
        resource = run.get("resource")
        if not isinstance(resource, dict) or resource.get("alloc_id") != alloc_id:
            raise CommandRejected(
                "resource-run-allocation-mismatch",
                f"run {run_id} was not authorized for allocation {alloc_id}",
            )
        conflicting = [
            other_id
            for other_id, other in state["aggregates"]["run"].items()
            if other_id != run_id
            and isinstance(other, dict)
            and isinstance(other.get("resource"), dict)
            and other["resource"].get("alloc_id") == alloc_id
            and other.get("status") in {"QUEUED", "RUNNING", "STALE"}
        ]
        if conflicting:
            raise CommandRejected(
                "resource-allocation-bound",
                f"allocation {alloc_id} is already reserved by {conflicting[0]}",
            )

    linked_job = allocation.get("job_id")
    if job_id is not None and linked_job not in {None, "", job_id}:
        raise CommandRejected(
            "resource-allocation-bound",
            f"allocation {alloc_id} is already linked to job {linked_job}",
        )


def _validate_allocation_gpu_binding(entry):
    count = entry.get("gpu_count", 0)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise RuleViolation(
            "allocation gpu_count must be an integer >= 0",
            rule="resource-gpu-count-invalid",
        )
    gpu_ids = entry.get("gpu_ids")
    gpu_type = entry.get("gpu_type")
    if count == 0:
        if gpu_ids is not None and gpu_ids != []:
            raise RuleViolation(
                "CPU allocation must not carry GPU ids",
                rule="resource-gpu-binding-invalid",
            )
        return
    if not isinstance(gpu_type, str) or not gpu_type.strip():
        raise RuleViolation(
            "GPU allocation requires one resolved gpu_type",
            rule="resource-gpu-type-required",
        )
    if (
        not isinstance(gpu_ids, list)
        or len(gpu_ids) != count
        or any(
            not isinstance(gpu_id, str)
            or not gpu_id
            or gpu_id != gpu_id.strip()
            for gpu_id in gpu_ids
        )
        or len(gpu_ids) != len(set(gpu_ids))
    ):
        raise RuleViolation(
            "GPU allocation requires exactly gpu_count unique physical gpu_ids",
            rule="resource-gpu-ids-required",
        )


def _validate_allocation_gpu_exclusivity(state, entry):
    count = entry.get("gpu_count", 0)
    if count <= 0:
        return
    requested = set(entry["gpu_ids"])
    for allocation in state["aggregates"]["resource_allocation"].values():
        if not isinstance(allocation, dict) or allocation.get("status") != "OPEN":
            continue
        if (
            allocation.get("server") != entry.get("server")
            or allocation.get("gpu_type") not in {
                None,
                entry.get("gpu_type"),
            }
        ):
            continue
        occupied = allocation.get("gpu_ids")
        allocated_count = allocation.get("gpu_count", 0)
        if (
            not isinstance(occupied, list)
            or not isinstance(allocated_count, int)
            or isinstance(allocated_count, bool)
            or len(occupied) != allocated_count
        ):
            raise CommandRejected(
                "resource-gpu-occupancy-indeterminate",
                "an open allocation has no deterministic physical GPU ids",
            )
        overlap = requested.intersection(occupied)
        if overlap:
            raise CommandRejected(
                "resource-gpu-id-overlap",
                "physical GPU ids are already allocated on this server/type: "
                f"{sorted(overlap)}",
            )


def _append_ledger(root, entry, *, idempotency_key=None, actor=None, policy=None):
    """Compatibility API that routes allocation lifecycle through EventStore."""
    if not isinstance(entry, dict):
        raise RuleViolation("allocation entry must be an object")
    try:
        canonical_json(entry)
    except (TypeError, ValueError) as exc:
        raise RuleViolation(
            "allocation entry must contain only JSON-compatible values"
        ) from exc
    alloc_id = entry.get("alloc_id")
    if not alloc_id:
        raise RuleViolation("allocation entry needs alloc_id")
    op = entry.get("op")
    store = _store(root)
    state = store.state()
    expected = int(
        state["aggregate_versions"].get(f"resource_allocation/{alloc_id}", 0)
    )
    effective_policy = policy
    if op == "allocate":
        _validate_allocation_gpu_binding(entry)
        event_type = "ResourceAllocationCreated"
        payload = {"record": {key: value for key, value in entry.items() if key != "op"}}
        caller_policy = effective_policy

        def allocation_policy(state, command):
            _validate_allocation_gpu_exclusivity(state, entry)
            if caller_policy is not None:
                caller_policy(state, command)

        effective_policy = allocation_policy
    elif op == "link":
        event_type = "ResourceAllocationLinked"
        payload = {
            "patch": {
                key: value for key, value in entry.items() if key not in {"op", "t"}
            }
        }
        caller_policy = effective_policy

        def link_policy(state, command):
            _validate_allocation_link(state, str(alloc_id), payload["patch"])
            if caller_policy is not None:
                caller_policy(state, command)

        effective_policy = link_policy
    elif op == "release":
        event_type = "ResourceAllocationReleased"
        payload = {
            "patch": {
                key: value for key, value in entry.items() if key not in {"op"}
            }
        }
    else:
        raise RuleViolation(f"unknown allocation op: {op!r}")
    try:
        research_management.update_resource_allocation(
            store.paths,
            str(alloc_id),
            event_type=event_type,
            payload=payload,
            expected_version=expected,
            actor=actor or {"type": "agent", "id": "resource-allocator"},
            idempotency_key=idempotency_key
            or f"allocation:{alloc_id}:{op}:{entry.get('t', '')}",
            policy=effective_policy,
        )
    except CommandRejected as exc:
        raise RuleViolation(
            exc.detail,
            rule=exc.rule,
            audited=exc.audited,
        ) from exc


def append_ledger(root, entry, *, idempotency_key=None, actor=None, policy=None):
    """Audit allocation lifecycle rejections before returning them to callers."""
    summary = {
        "operation": entry.get("op") if isinstance(entry, dict) else None,
        "alloc_id": entry.get("alloc_id") if isinstance(entry, dict) else None,
        "server": entry.get("server") if isinstance(entry, dict) else None,
        "package_id": (
            entry.get("package_id") or entry.get("pkg")
            if isinstance(entry, dict)
            else None
        ),
        "experiment_id": (
            entry.get("experiment_id") or entry.get("exp_id")
            if isinstance(entry, dict)
            else None
        ),
        "gpu_count": entry.get("gpu_count") if isinstance(entry, dict) else None,
        "gpu_type": entry.get("gpu_type") if isinstance(entry, dict) else None,
        "gpu_ids": entry.get("gpu_ids") if isinstance(entry, dict) else None,
        "run_id": entry.get("run_id") if isinstance(entry, dict) else None,
        "job_id": entry.get("job_id") if isinstance(entry, dict) else None,
        "outcome": entry.get("outcome") if isinstance(entry, dict) else None,
    }
    try:
        return _append_ledger(
            root,
            entry,
            idempotency_key=idempotency_key,
            actor=actor,
            policy=policy,
        )
    except RuleViolation as exc:
        audit_rejection(
            root,
            command="resource-allocation",
            payload=summary,
            error=exc,
            actor=actor,
        )
        raise


def open_allocations(root):
    state = _store(root).state()
    rows = state["aggregates"]["resource_allocation"]
    first_seq = {}
    for event in _store(root).events():
        if (
            event["aggregate_type"] == "resource_allocation"
            and event["event_type"] == "ResourceAllocationCreated"
        ):
            first_seq.setdefault(event["aggregate_id"], event["seq"])
    return [
        dict(rows[alloc_id])
        for alloc_id in sorted(rows, key=lambda key: first_seq.get(key, 10**18))
        if rows[alloc_id].get("status") == "OPEN"
    ]
