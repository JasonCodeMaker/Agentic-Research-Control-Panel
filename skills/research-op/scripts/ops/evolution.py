"""Self-evolve mutation handlers.

Project memory is committed as Learning, Decision, and Rule events in the
shared management store.  Generated Skill bundles and their install lifecycle
remain in ``<project>/.agents/self-evolve`` outside workspace ``.research``.
"""

import json
import os
from pathlib import Path

from lib.research_state import CommandRejected, ResearchPaths
from lib.self_evolve import (
    bundle,
    install,
    lifecycle,
    sandbox,
    schema,
    skill_lifecycle,
    state as memory,
    store,
)

import management

EVOLUTION_OPS = ("evolution-observe", "evolution-create", "evolution-evidence-add",
                 "evolution-transition", "evolution-project", "evolution-check",
                 "evolution-approve", "evolution-install-skill",
                 "evolution-suspend-skill", "evolution-rollback-skill")

_R3R4 = ("R3_PROJECT_EXEC", "R4_TRUST_BOUNDARY")


class EvolutionReject(Exception):
    """Reject-before-write: a record broke an invariant; no bytes hit disk."""

    def __init__(self, rule, detail):
        self.rule = rule
        self.detail = detail
        super().__init__(detail)


def _skills_log(root):
    return Path(root) / "skills" / "transitions.jsonl"


def _approvals_log(root):
    return Path(root) / "approvals" / "approvals.jsonl"


def _append_jsonl(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def run(op, payload, root, project_root=None):
    """Dispatch one evolution op. Returns (status, files, message)."""
    supplied_root = root
    paths = memory.resolve_paths(root)
    project_root = (
        Path(project_root).resolve()
        if project_root is not None
        else paths.workspace
    )
    # A caller may explicitly supply an external self-evolve tool directory.
    # ResearchPaths callers use the canonical user/tool-side location.
    supplied_is_paths = isinstance(supplied_root, ResearchPaths) or (
        hasattr(supplied_root, "workspace")
        and hasattr(supplied_root, "root")
        and hasattr(supplied_root, "events")
        and hasattr(supplied_root, "current")
    )
    skill_root = (
        project_root / ".agents" / "self-evolve"
        if supplied_is_paths
        or Path(supplied_root).expanduser().resolve() == paths.root
        else Path(supplied_root).expanduser().resolve()
    )
    handlers = {
        "evolution-observe": lambda value: _observe(value, paths),
        "evolution-evidence-add": lambda value: _evidence_add(value, paths),
        "evolution-transition": lambda value: _transition(value, paths, skill_root),
        "evolution-project": lambda value: _project(value, paths, skill_root),
        "evolution-check": lambda value: _check(value, paths, skill_root),
    }
    deploy_handlers = {
        "evolution-approve": _approve,
        "evolution-install-skill": _install_skill,
        "evolution-suspend-skill": _suspend_skill,
        "evolution-rollback-skill": _rollback_skill,
    }
    if op == "evolution-create":
        if "manifest" in payload:
            return _create_skill(payload, skill_root)
        return _create_rule(payload, paths)
    if op in handlers:
        return handlers[op](payload)
    if op in deploy_handlers:
        return deploy_handlers[op](payload, skill_root, project_root)
    raise EvolutionReject("unknown-op", f"unknown evolution op: {op}")


def _observe(payload, root):
    try:
        schema.validate_event(payload)
    except schema.SchemaViolation as e:
        raise EvolutionReject("event-schema", str(e))
    learning_id = str(payload.get("learning_id") or f"learning:{payload['event_id']}")
    record = {
        "id": learning_id,
        "observation": payload.get("observation") or payload.get("subject") or payload["type"],
        "signal_type": payload["type"],
        "source": payload["source"],
        "source_event_id": payload["event_id"],
        "scope": payload.get("scope"),
        "evidence_refs": payload.get("evidence_refs"),
        "status": "OBSERVED",
    }
    try:
        event = management.commit_evolution_learning(
            root,
            record,
            idempotency_key=payload["idempotency_key"],
        )
    except CommandRejected as exc:
        raise EvolutionReject(exc.rule, exc.detail) from exc
    return (
        "PASSED",
        [str(root.events), str(root.current)],
        f"observed {payload['type']} as {learning_id} ({event['event_id']})",
    )


def _create_skill(payload, root):
    manifest = payload["manifest"]
    files = payload.get("files", {})
    try:
        schema.validate_skill_manifest(manifest)
    except schema.SchemaViolation as e:
        raise EvolutionReject("skill-schema", str(e))
    viol = sandbox.permission_violations(manifest)
    if viol:
        raise EvolutionReject("sandbox-violation", "; ".join(viol))
    if files and not bundle.verify_bundle(files, manifest.get("bundle_digest")):
        raise EvolutionReject("bundle-mismatch", "files do not reproduce bundle_digest")
    eid, ver = manifest["id"], manifest["version"]
    t = {
        "schema_version": schema.TRANSITION_SCHEMA,
        "transition_id": f"trn-create-skill-{eid}-{ver}",
        "store": "skill", "entity_id": eid, "entity_version": ver,
        "expected_from_state": "OBSERVED", "to_state": "CANDIDATE", "op": "create",
        "risk_class": manifest["risk_class"],
        "idempotency_key": f"create-skill:{eid}:{ver}",
        "evidence_refs": [], "approval_ref": None,
    }
    schema.validate_transition(t)
    skill_lifecycle.validate_edge("OBSERVED", "CANDIDATE")
    try:
        _, skipped = store.append_transition(_skills_log(root), t)
    except store.ConcurrencyConflict as e:
        raise EvolutionReject("concurrency", str(e))
    if skipped:
        return "skipped", [], f"skill candidate {eid}@{ver} already exists"
    base = Path(root) / "skills" / "candidates" / eid / ver
    _write_json(base / "manifest.json", manifest)
    touched = [str(base / "manifest.json"), str(_skills_log(root))]
    for name, content in files.items():
        p = base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        touched.append(str(p))
    return "PASSED",touched, f"skill candidate {eid}@{ver} created"


def _create_rule(payload, root):
    rule = payload
    try:
        schema.validate_rule(rule)
    except schema.SchemaViolation as e:
        raise EvolutionReject("rule-schema", str(e))
    learning_id = memory.learning_aggregate_id(rule["id"], rule["version"])
    learning = {
        "id": learning_id,
        "observation": rule.get("description") or rule["content"],
        "candidate_rule": rule,
        "scope": rule["scope"],
        "evidence_refs": rule.get("evidence_refs"),
        "status": "CANDIDATE",
        "origin": "selfevolve",
    }
    try:
        event = management.commit_evolution_learning(
            root,
            learning,
            idempotency_key=f"create:{rule['id']}:{rule['version']}",
        )
    except CommandRejected as exc:
        raise EvolutionReject(exc.rule, exc.detail) from exc
    return (
        "PASSED",
        [str(root.events), str(root.current)],
        f"candidate Learning {learning_id} created ({event['event_id']})",
    )


def _evidence_add(payload, root):
    try:
        schema.validate_evidence(payload)
    except schema.SchemaViolation as e:
        raise EvolutionReject("evidence-schema", str(e))
    learning_id = memory.learning_aggregate_id(
        payload["entity_id"], payload["entity_version"]
    )
    decision = {
        "id": str(payload["evidence_id"]),
        "decision_type": "ORACLE",
        "subject_id": learning_id,
        "oracle": payload["oracle"],
        "outcome": payload["oracle"]["result"],
        "stage": payload["stage"],
        "evidence_refs": payload.get("evidence_refs"),
    }
    try:
        event = management.commit_evolution_decision(
            root,
            decision,
            idempotency_key=str(
                payload.get("idempotency_key")
                or f"oracle:{learning_id}:{payload['evidence_id']}"
            ),
        )
    except CommandRejected as exc:
        raise EvolutionReject(exc.rule, exc.detail) from exc
    return (
        "PASSED",
        [str(root.events), str(root.current)],
        f"oracle Decision {payload['evidence_id']} = "
        f"{payload['oracle']['result']} ({event['event_id']})",
    )


def _transition(payload, root, skill_root=None):
    t = payload
    try:
        schema.validate_transition(t)
    except schema.SchemaViolation as e:
        raise EvolutionReject("transition-schema", str(e))
    if t["store"] == "skill":
        return _transition_skill(t, skill_root)
    try:
        lifecycle.validate_edge(t["expected_from_state"], t["to_state"])
    except lifecycle.IllegalTransition as e:
        raise EvolutionReject("illegal-edge", str(e))
    # R3/R4 candidates are parked: never auto-promote to RULE_ACTIVE without an approval.
    if t["to_state"] == "RULE_ACTIVE" and t["risk_class"] in _R3R4 and not t.get("approval_ref"):
        raise EvolutionReject("needs-approval",
                              f"{t['risk_class']} promotion to active requires approval_ref")
    current = memory.lifecycle_state(root, t["entity_id"], t["entity_version"])
    if current != t["expected_from_state"]:
        raise EvolutionReject(
            "concurrency",
            f"{t['entity_id']}@{t['entity_version']}: "
            f"expected_from_state={t['expected_from_state']!r} but current={current!r}",
        )
    learning_id = memory.learning_aggregate_id(t["entity_id"], t["entity_version"])
    decision_id = str(t["transition_id"])
    retiring = t["expected_from_state"] == "RULE_ACTIVE" and t["to_state"] in {
        "RULE_SUPERSEDED",
        "INVALIDATED",
    }
    candidate = None
    if t["to_state"] == "RULE_ACTIVE":
        state = memory.management_state(root)
        learning = state["aggregates"]["learning"].get(learning_id)
        candidate = (
            learning.get("candidate_rule")
            if isinstance(learning, dict)
            and isinstance(learning.get("candidate_rule"), dict)
            else None
        )
        if candidate is None:
            raise EvolutionReject(
                "promotion-candidate-missing",
                f"Learning {learning_id} has no immutable candidate_rule",
            )
        try:
            memory.preflight_promotion(
                root,
                learning_id=learning_id,
                rule=candidate,
                admission=t.get("admission"),
            )
        except CommandRejected as exc:
            raise EvolutionReject(exc.rule, exc.detail) from exc
    elif retiring:
        try:
            memory.preflight_retirement(
                root,
                rule_id=t["entity_id"],
                version=t["entity_version"],
            )
        except CommandRejected as exc:
            raise EvolutionReject(exc.rule, exc.detail) from exc
    subject_id = (
        memory.rule_aggregate_id(t["entity_id"], t["entity_version"])
        if retiring
        else learning_id
    )
    decision = {
        "id": decision_id,
        "decision_type": (
            "ADMISSION" if t["to_state"] == "RULE_ACTIVE" else "RULE_LIFECYCLE"
        ),
        "subject_id": subject_id,
        "from_state": t["expected_from_state"],
        "to_state": t["to_state"],
        "outcome": t.get("admission") or t["to_state"],
        "admission": t.get("admission"),
        "risk_class": t["risk_class"],
        "approval_ref": t.get("approval_ref"),
        "reason": t.get("reason"),
        "evidence_refs": t.get("evidence_refs"),
    }
    try:
        management.commit_evolution_decision(
            root,
            decision,
            idempotency_key=f"decision:{t['idempotency_key']}",
        )
    except CommandRejected as exc:
        raise EvolutionReject(exc.rule, exc.detail) from exc
    files = [str(root.events), str(root.current)]
    if t["to_state"] == "RULE_ACTIVE":
        assert candidate is not None
        try:
            management.commit_evolution_rule_promotion(
                root,
                learning_id=learning_id,
                decision_id=decision_id,
                rule=candidate,
                idempotency_key=f"promote:{t['idempotency_key']}",
            )
        except CommandRejected as exc:
            raise EvolutionReject(exc.rule, exc.detail) from exc
    elif retiring:
        try:
            management.commit_evolution_rule_retirement(
                root,
                rule_id=t["entity_id"],
                version=t["entity_version"],
                decision_id=decision_id,
                lifecycle_state=t["to_state"],
                idempotency_key=f"retire:{t['idempotency_key']}",
            )
        except CommandRejected as exc:
            raise EvolutionReject(exc.rule, exc.detail) from exc
    return (
        "PASSED",
        files,
        f"{t['entity_id']}@{t['entity_version']} -> {t['to_state']}",
    )


def _transition_skill(t, root):
    """Skill-store state moves that do NOT grant authority; install/restore/rollback use their own ops."""
    try:
        skill_lifecycle.validate_edge(t["expected_from_state"], t["to_state"])
    except skill_lifecycle.IllegalTransition as e:
        raise EvolutionReject("illegal-edge", str(e))
    if skill_lifecycle.requires_approval(t["expected_from_state"], t["to_state"]):
        raise EvolutionReject(
            "use-dedicated-op",
            "install/restore/rollback require evolution-install-skill / evolution-rollback-skill")
    try:
        _, skipped = store.append_transition(_skills_log(root), t)
    except store.ConcurrencyConflict as e:
        raise EvolutionReject("concurrency", str(e))
    files = [str(_skills_log(root))]
    if not skipped and t["to_state"] == "VALIDATED":
        files += _seal_skill_release(root, t["entity_id"], t["entity_version"])
    suffix = " (already applied)" if skipped else ""
    return ("skipped" if skipped else "passed"), files, \
        f"skill {t['entity_id']}@{t['entity_version']} -> {t['to_state']}{suffix}"


def _seal_skill_release(root, eid, ver):
    """Copy the immutable candidate bundle into releases/ at the validated boundary."""
    src = Path(root) / "skills" / "candidates" / eid / ver
    if not src.exists():
        return []
    dst = Path(root) / "skills" / "releases" / eid / ver
    if dst.exists():
        return [str(dst)]
    import shutil
    shutil.copytree(src, dst)
    return [str(dst)]


def _load_release_manifest(root, eid, ver):
    p = Path(root) / "skills" / "releases" / eid / ver / "manifest.json"
    if not p.exists():
        raise EvolutionReject("no-release", f"no sealed release {eid}@{ver}")
    return json.loads(p.read_text(encoding="utf-8"))


def _load_approval(payload, root):
    if isinstance(payload.get("approval"), dict):
        return payload["approval"]
    aid = payload.get("approval_id")
    log = _approvals_log(root)
    if aid and log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("approval_id") == aid:
                return json.loads(line)
    raise EvolutionReject("no-approval", "approval not found")


def _skill_transition(root, eid, ver, frm, to, op, *, approval_ref=None, reason=None):
    t = {"schema_version": schema.TRANSITION_SCHEMA,
         "transition_id": f"trn-{op}-{eid}-{ver}-{to}", "store": "skill",
         "entity_id": eid, "entity_version": ver, "expected_from_state": frm, "to_state": to,
         "op": op, "risk_class": "R3_PROJECT_EXEC",
         "idempotency_key": f"{op}:{eid}:{ver}:{to}",
         "approval_ref": approval_ref, "reason": reason}
    schema.validate_transition(t)
    return store.append_transition(_skills_log(root), t)


def _approve(payload, root, project_root):
    """Append a user approval. Trust gate: the background Worker may NOT approve as user (§9.6)."""
    actor = os.environ.get("RESEARCH_OP_AGENT", "main")
    if "worker" in actor:
        raise EvolutionReject("worker-cannot-approve",
                              "evolution-approve requires a trusted interactive actor, not the Worker")
    try:
        schema.validate_approval(payload)
    except schema.SchemaViolation as e:
        raise EvolutionReject("approval-schema", str(e))
    if payload.get("approved_by") != "user":
        raise EvolutionReject("approval-not-user", "approved_by must be 'user'")
    log = _approvals_log(root)
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("approval_id") == payload["approval_id"]:
                return "skipped", [], f"approval {payload['approval_id']} already recorded"
    _append_jsonl(log, payload)
    return "PASSED",[str(log)], f"approval {payload['approval_id']} {payload['decision']}"


def _install_skill(payload, root, project_root):
    eid, ver = payload["entity_id"], payload["entity_version"]
    manifest = _load_release_manifest(root, eid, ver)
    approval = _load_approval(payload, root)
    cur = store.current_state(store.read_log(_skills_log(root)), eid, ver)
    if cur != "AWAITING_INSTALL_APPROVAL":
        raise EvolutionReject("bad-state", f"{eid}@{ver} is {cur}, expected AWAITING_INSTALL_APPROVAL")
    _skill_transition(root, eid, ver, "AWAITING_INSTALL_APPROVAL", "INSTALLING", "install",
                      approval_ref=approval.get("approval_id"))
    try:
        dest, link = install.install_skill(root, project_root, manifest, approval,
                                           now=payload.get("now"))
    except install.InstallError as e:
        _skill_transition(root, eid, ver, "INSTALLING", "INSTALL_FAILED", "install-fail",
                          reason=e.detail)
        raise EvolutionReject(e.rule, e.detail)
    _skill_transition(root, eid, ver, "INSTALLING", "CANARY", "install",
                      approval_ref=approval.get("approval_id"))
    return "PASSED",[str(link), str(_skills_log(root))], f"installed {eid}@{ver} -> canary at {link}"


def _suspend_skill(payload, root, project_root):
    """Authority-removing: always allowed automatically (§7.2)."""
    eid, ver = payload["entity_id"], payload["entity_version"]
    cur = store.current_state(store.read_log(_skills_log(root)), eid, ver)
    if cur not in ("CANARY", "SKILL_ACTIVE"):
        raise EvolutionReject("bad-state", f"cannot suspend {eid}@{ver} from {cur}")
    _skill_transition(root, eid, ver, cur, "SUSPENDED", "suspend", reason=payload.get("reason"))
    return "PASSED",[str(_skills_log(root))], f"suspended {eid}@{ver} (was {cur})"


def _rollback_skill(payload, root, project_root):
    eid = payload["entity_id"]
    target_ver = payload["target_version"]
    manifest = _load_release_manifest(root, eid, target_ver)
    ok, reason = install.authorize_rollback(
        target_version=target_ver,
        current_approval=payload.get("approval"),
        pre_authorization=payload.get("pre_authorization"))
    if not ok:
        raise EvolutionReject("rollback-unauthorized", reason)
    # target must be an intact previously-superseded release
    cur = store.current_state(store.read_log(_skills_log(root)), eid, target_ver)
    if cur != "SKILL_SUPERSEDED":
        raise EvolutionReject("bad-state", f"rollback target {eid}@{target_ver} is {cur}, expected SKILL_SUPERSEDED")
    dest = (Path(project_root) / ".claude" / "skills" / ".versions" / eid
            / install._version_dirname(target_ver, manifest["bundle_digest"]))
    if not dest.exists():
        raise EvolutionReject("no-installed-target", f"no intact installed release {eid}@{target_ver}")
    install._atomic_symlink(Path(project_root) / ".claude" / "skills" / eid, dest)
    _skill_transition(root, eid, target_ver, "SKILL_SUPERSEDED", "CANARY", "rollback",
                      reason=f"rollback ({reason})")
    return "PASSED",[str(_skills_log(root))], f"rolled back to {eid}@{target_ver} ({reason})"


def _fold_states(log):
    return {f"{eid}@{ver}": st for (eid, ver), st in store.fold(store.read_log(log)).items()}


def _project(payload, root, skill_root):
    """Build an ephemeral consistency view; no project-memory projection is persisted."""
    state = memory.management_state(root)
    rules = {
        key: value.get("lifecycle_state") or value.get("status")
        for key, value in sorted(state["aggregates"]["rule"].items())
    }
    skills = _fold_states(_skills_log(skill_root))
    return (
        "PASSED",
        [],
        f"projected {len(rules)} rule + {len(skills)} skill versions in memory",
    )


def _check(payload, root, skill_root):
    state = memory.management_state(root)
    skills = store.fold(store.read_log(_skills_log(skill_root)))
    problems = []
    for (eid, ver) in skills:
        if not (Path(skill_root) / "skills" / "candidates" / eid / ver / "manifest.json").exists():
            problems.append(f"missing-skill-candidate:{eid}@{ver}")
    for rule_id, rule in state["aggregates"]["rule"].items():
        if rule.get("origin") == "selfevolve":
            source = rule.get("source_learning_id")
            decision = rule.get("promotion_decision_id")
            if source not in state["aggregates"]["learning"]:
                problems.append(f"missing-rule-learning:{rule_id}")
            if decision not in state["aggregates"]["decision"]:
                problems.append(f"missing-rule-decision:{rule_id}")
            try:
                schema.validate_evidence_refs(rule.get("evidence_refs"))
            except schema.SchemaViolation:
                problems.append(f"missing-rule-evidence:{rule_id}")
    if problems:
        raise EvolutionReject("consistency", "; ".join(problems))
    return (
        "PASSED",
        [],
        f"consistent: {len(state['aggregates']['rule'])} rule + "
        f"{len(skills)} skill versions",
    )
