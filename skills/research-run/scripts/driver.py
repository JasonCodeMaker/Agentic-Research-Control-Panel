"""Stage-0 production-loop contract: the agent-driven dispatch seam.

The driver replaces `skeleton.run`'s hard-wired stub chain as the *production* locus: it runs role
adapters in order (a fake adapter in tests, a real sub-agent dispatch later), validates each typed
role return, and collects the proposed research-op mutation envelopes + a PACK continuity candidate.
It never writes a package surface itself — every mutation is emitted as a research-op envelope, and a
role that tries to write a file directly is refused. `skeleton.run` stays as the L1 reference fixture.
"""

import sys
from pathlib import Path

_PIPE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PIPE / "lib"))
sys.path.insert(0, str(_PIPE / "skills" / "research-op" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scope_ssot  # noqa: E402
import transitions  # noqa: E402
import pack  # noqa: E402

# Typed role-return contract every dispatched role must satisfy.
ROLE_RETURN_FIELDS = ("agent_role", "assigned_scope", "status", "evidence",
                      "blockers", "recommended_next_action", "global_scope_version",
                      "sourceDirection", "sourceTask")
ROLE_STATUSES = {"ROLE_OK", "ROLE_BLOCKED", "ROLE_FAILED"}

# Mutation envelope contract — the only way a role may change a surface (always via research-op).
ENVELOPE_FIELDS = {"op", "target", "payload"}
ALLOWED_OPS = {"insert", "update", "delete", "check", "scan-events",
               "scope-transition", "registry-add"}
_SURFACE_OPS = {"insert", "update", "delete"}  # these must name a known research-op target


def validate_mutation(env):
    """Return a list of reasons this mutation is not a legal research-op envelope (empty = legal)."""
    if not isinstance(env, dict):
        return ["mutation must be an object"]
    errs = []
    if set(env.keys()) != ENVELOPE_FIELDS:
        errs.append(f"envelope keys must be exactly {sorted(ENVELOPE_FIELDS)}; got {sorted(env.keys())}")
    if env.get("op") not in ALLOWED_OPS:
        errs.append(f"op {env.get('op')!r} is not a research-op op (no direct file writes)")
    if env.get("op") in _SURFACE_OPS and env.get("target") not in transitions.TARGETS:
        errs.append(f"target {env.get('target')!r} is not a known research-op target")
    if "payload" in env and not isinstance(env["payload"], dict):
        errs.append("payload must be an object")
    return errs


def validate_role_return(ret, *, context=None):
    """Return a list of reasons this role return violates the typed contract (empty = valid)."""
    if not isinstance(ret, dict):
        return ["role return must be an object"]
    context = context or {}
    errs = [f"missing field: {f}" for f in ROLE_RETURN_FIELDS if f not in ret]
    if errs:
        return errs
    if ret["status"] not in ROLE_STATUSES:
        errs.append(f"status {ret['status']!r} not in {sorted(ROLE_STATUSES)}")
    if ret["status"] == "ROLE_OK" and not ret["evidence"]:
        errs.append("status 'ROLE_OK' requires non-empty evidence")
    if ret["status"] == "ROLE_BLOCKED" and not ret["blockers"]:
        errs.append("status 'ROLE_BLOCKED' requires a non-empty blockers list")
    expected_version = context.get("global_scope_version")
    if expected_version is not None and ret.get("global_scope_version") != expected_version:
        errs.append(
            f"stale scope report: global_scope_version {ret.get('global_scope_version')!r} "
            f"does not match current {expected_version!r}"
        )
    if not ret.get("sourceDirection"):
        errs.append("sourceDirection must be non-empty")
    if not ret.get("sourceTask"):
        errs.append("sourceTask must be non-empty")
    for env in ret.get("mutations", []):
        errs += [f"mutation: {e}" for e in validate_mutation(env)]
    return errs


def _pack_candidate(node, role_returns):
    """Assemble a complete PACK bundle from the tick so an absent reader never sees a blank field."""
    evidence = [e for r in role_returns for e in r.get("evidence", [])]
    blockers = [b for r in role_returns for b in r.get("blockers", [])]
    last = role_returns[-1] if role_returns else {}
    return {
        "attempted": ", ".join(r["agent_role"] for r in role_returns) or "none",
        "found": "; ".join(map(str, evidence)) or "none",
        "hypothesis_state": node["spec"]["hypothesis"],
        "next_action": last.get("recommended_next_action") or "none",
        "blocking_decision": "; ".join(map(str, blockers)) or "none",
    }


def run_tick(pkg_id, scope_node, role_sequence, adapters, *, context=None, pack_log=None):
    """Dry-run one dispatch tick: run each role adapter in order, validate its return, collect the
    proposed research-op mutations + a PACK candidate. Halts at the first invalid return. Writes no
    package surface; writes the PACK candidate only if pack_log is given."""
    scope_ssot.validate_node(scope_node)  # malformed spec stops the tick before any role runs
    ctx = dict(context or {})
    ctx["scope_node"] = scope_node
    roles_run, role_returns, proposed = [], [], []
    rejection = None
    for role in role_sequence:
        ret = adapters[role](ctx)
        errs = validate_role_return(ret, context=ctx)
        if errs:
            rejection = {"role": role, "errors": errs}
            break
        roles_run.append(role)
        role_returns.append(ret)
        proposed += ret.get("mutations", [])
        ctx.setdefault("evidence", []).extend(ret["evidence"])
    candidate = _pack_candidate(scope_node, role_returns)
    if rejection is None and pack_log is not None:
        pack.write_pack(pack_log, candidate)
    return {
        "pkg": pkg_id, "roles_run": roles_run, "role_returns": role_returns,
        "proposed_mutations": [] if rejection else proposed,
        "pack_candidate": candidate, "rejection": rejection,
    }
