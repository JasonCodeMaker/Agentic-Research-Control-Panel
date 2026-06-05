"""evolution-* ops — the v1 Rule Store mutation handlers (plan §9.7).

Project-level, like scope-transition/registry-add: no owning package, so they bypass the
package (category, status) state machine. Reject-before-write; the caller audits + prints.
`run()` returns (status, files, message); rejections raise EvolutionReject.
"""

import json
import os
from pathlib import Path

from self_evolve import schema, lifecycle, store, sandbox, bundle, skill_lifecycle, install

EVOLUTION_OPS = ("evolution-observe", "evolution-create", "evolution-evidence-add",
                 "evolution-transition", "evolution-project", "evolution-check",
                 "evolution-approve", "evolution-install-skill",
                 "evolution-suspend-skill", "evolution-rollback-skill")

_R3R4 = ("R3-project-exec", "R4-trust-boundary")


class EvolutionReject(Exception):
    """Reject-before-write: a record broke an invariant; no bytes hit disk."""

    def __init__(self, rule, detail):
        self.rule = rule
        self.detail = detail
        super().__init__(detail)


def _rules_log(root):
    return Path(root) / "rules" / "transitions.jsonl"


def _skills_log(root):
    return Path(root) / "skills" / "transitions.jsonl"


def _approvals_log(root):
    return Path(root) / "approvals" / "approvals.jsonl"


def _events_log(root):
    return Path(root) / "events" / "events.jsonl"


def _append_jsonl(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def run(op, payload, root, project_root=None):
    """Dispatch one evolution op. Returns (status, files, message)."""
    root = Path(root)
    project_root = Path(project_root) if project_root is not None else Path.cwd()
    handlers = {
        "evolution-observe": _observe,
        "evolution-create": _create,
        "evolution-evidence-add": _evidence_add,
        "evolution-transition": _transition,
        "evolution-project": _project,
        "evolution-check": _check,
    }
    deploy_handlers = {
        "evolution-approve": _approve,
        "evolution-install-skill": _install_skill,
        "evolution-suspend-skill": _suspend_skill,
        "evolution-rollback-skill": _rollback_skill,
    }
    if op in handlers:
        return handlers[op](payload, root)
    if op in deploy_handlers:
        return deploy_handlers[op](payload, root, project_root)
    raise EvolutionReject("unknown-op", f"unknown evolution op: {op}")


def _observe(payload, root):
    try:
        schema.validate_event(payload)
    except schema.SchemaViolation as e:
        raise EvolutionReject("event-schema", str(e))
    log = _events_log(root)
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("idempotency_key") == payload["idempotency_key"]:
                return "skipped", [], f"duplicate event {payload['event_id']}"
    _append_jsonl(log, payload)
    return "passed", [str(log)], f"observed {payload['type']} {payload['event_id']}"


def _create(payload, root):
    """Seal a Rule (bare rule dict) or a Skill candidate ({manifest, files})."""
    if "manifest" in payload:
        return _create_skill(payload, root)
    return _create_rule(payload, root)


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
        "expected_from_state": "observed", "to_state": "candidate", "op": "create",
        "risk_class": manifest["risk_class"],
        "idempotency_key": f"create-skill:{eid}:{ver}",
        "evidence_refs": [], "approval_ref": None,
    }
    schema.validate_transition(t)
    skill_lifecycle.validate_edge("observed", "candidate")
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
    return "passed", touched, f"skill candidate {eid}@{ver} created"


def _create_rule(payload, root):
    rule = payload
    try:
        schema.validate_rule(rule)
    except schema.SchemaViolation as e:
        raise EvolutionReject("rule-schema", str(e))
    cand = Path(root) / "rules" / "candidates" / rule["id"] / rule["version"] / "rule.json"
    t = {
        "schema_version": schema.TRANSITION_SCHEMA,
        "transition_id": f"trn-create-{rule['id']}-{rule['version']}",
        "store": "rule", "entity_id": rule["id"], "entity_version": rule["version"],
        "expected_from_state": "observed", "to_state": "candidate", "op": "create",
        "risk_class": rule["risk_class"],
        "idempotency_key": f"create:{rule['id']}:{rule['version']}",
        "evidence_refs": [], "approval_ref": None,
    }
    schema.validate_transition(t)
    lifecycle.validate_edge("observed", "candidate")
    try:
        _, skipped = store.append_transition(_rules_log(root), t)
    except store.ConcurrencyConflict as e:
        raise EvolutionReject("concurrency", str(e))
    if skipped:
        return "skipped", [], f"candidate {rule['id']}@{rule['version']} already exists"
    _write_json(cand, rule)
    return "passed", [str(cand), str(_rules_log(root))], f"candidate {rule['id']}@{rule['version']} created"


def _evidence_add(payload, root):
    try:
        schema.validate_evidence(payload)
    except schema.SchemaViolation as e:
        raise EvolutionReject("evidence-schema", str(e))
    p = (Path(root) / "evidence" / payload["entity_id"] / payload["entity_version"]
         / f"{payload['evidence_id']}.json")
    _write_json(p, payload)
    return "passed", [str(p)], f"evidence {payload['evidence_id']} = {payload['oracle']['result']}"


def _transition(payload, root):
    t = payload
    try:
        schema.validate_transition(t)
    except schema.SchemaViolation as e:
        raise EvolutionReject("transition-schema", str(e))
    if t["store"] == "skill":
        return _transition_skill(t, root)
    try:
        lifecycle.validate_edge(t["expected_from_state"], t["to_state"])
    except lifecycle.IllegalTransition as e:
        raise EvolutionReject("illegal-edge", str(e))
    # R3/R4 candidates are parked: never auto-promote to active without an approval.
    if t["to_state"] == "active" and t["risk_class"] in _R3R4 and not t.get("approval_ref"):
        raise EvolutionReject("needs-approval",
                              f"{t['risk_class']} promotion to active requires approval_ref")
    try:
        _, skipped = store.append_transition(_rules_log(root), t)
    except store.ConcurrencyConflict as e:
        raise EvolutionReject("concurrency", str(e))
    if skipped:
        return "skipped", [], f"{t['entity_id']}@{t['entity_version']} -> {t['to_state']} (already applied)"
    files = [str(_rules_log(root))]
    if t["to_state"] == "active":
        files += _seal_release(root, t["entity_id"], t["entity_version"])
    return "passed", files, f"{t['entity_id']}@{t['entity_version']} -> {t['to_state']}"


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
    if not skipped and t["to_state"] == "validated":
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
         "op": op, "risk_class": "R3-project-exec",
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
    return "passed", [str(log)], f"approval {payload['approval_id']} {payload['decision']}"


def _install_skill(payload, root, project_root):
    eid, ver = payload["entity_id"], payload["entity_version"]
    manifest = _load_release_manifest(root, eid, ver)
    approval = _load_approval(payload, root)
    cur = store.current_state(store.read_log(_skills_log(root)), eid, ver)
    if cur != "awaiting_install_approval":
        raise EvolutionReject("bad-state", f"{eid}@{ver} is {cur}, expected awaiting_install_approval")
    _skill_transition(root, eid, ver, "awaiting_install_approval", "installing", "install",
                      approval_ref=approval.get("approval_id"))
    try:
        dest, link = install.install_skill(root, project_root, manifest, approval,
                                           now=payload.get("now"))
    except install.InstallError as e:
        _skill_transition(root, eid, ver, "installing", "install_failed", "install-fail",
                          reason=e.detail)
        raise EvolutionReject(e.rule, e.detail)
    _skill_transition(root, eid, ver, "installing", "canary", "install",
                      approval_ref=approval.get("approval_id"))
    return "passed", [str(link), str(_skills_log(root))], f"installed {eid}@{ver} -> canary at {link}"


def _suspend_skill(payload, root, project_root):
    """Authority-removing: always allowed automatically (§7.2)."""
    eid, ver = payload["entity_id"], payload["entity_version"]
    cur = store.current_state(store.read_log(_skills_log(root)), eid, ver)
    if cur not in ("canary", "active"):
        raise EvolutionReject("bad-state", f"cannot suspend {eid}@{ver} from {cur}")
    _skill_transition(root, eid, ver, cur, "suspended", "suspend", reason=payload.get("reason"))
    return "passed", [str(_skills_log(root))], f"suspended {eid}@{ver} (was {cur})"


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
    if cur != "superseded":
        raise EvolutionReject("bad-state", f"rollback target {eid}@{target_ver} is {cur}, expected superseded")
    dest = (Path(project_root) / ".claude" / "skills" / ".versions" / eid
            / install._version_dirname(target_ver, manifest["bundle_digest"]))
    if not dest.exists():
        raise EvolutionReject("no-installed-target", f"no intact installed release {eid}@{target_ver}")
    install._atomic_symlink(Path(project_root) / ".claude" / "skills" / eid, dest)
    _skill_transition(root, eid, target_ver, "superseded", "canary", "rollback",
                      reason=f"rollback ({reason})")
    return "passed", [str(_skills_log(root))], f"rolled back to {eid}@{target_ver} ({reason})"


def _seal_release(root, eid, ver):
    src = Path(root) / "rules" / "candidates" / eid / ver / "rule.json"
    if not src.exists():
        return []
    dst = Path(root) / "rules" / "releases" / eid / ver / "rule.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return [str(dst)]


def _fold_states(log):
    return {f"{eid}@{ver}": st for (eid, ver), st in store.fold(store.read_log(log)).items()}


def _project(payload, root):
    rules = _fold_states(_rules_log(root))
    skills = _fold_states(_skills_log(root))
    p = Path(root) / "projections" / "current-state.json"
    _write_json(p, {"rules": rules, "skills": skills})
    return "passed", [str(p)], f"projected {len(rules)} rule + {len(skills)} skill versions"


def _check(payload, root):
    rules = store.fold(store.read_log(_rules_log(root)))
    skills = store.fold(store.read_log(_skills_log(root)))
    problems = []
    proj = Path(root) / "projections" / "current-state.json"
    if proj.exists():
        got = json.loads(proj.read_text(encoding="utf-8"))
        if {f"{e}@{v}": s for (e, v), s in rules.items()} != got.get("rules", {}):
            problems.append("projection-drift:rules")
        if {f"{e}@{v}": s for (e, v), s in skills.items()} != got.get("skills", {}):
            problems.append("projection-drift:skills")
    for (eid, ver) in rules:
        if not (Path(root) / "rules" / "candidates" / eid / ver / "rule.json").exists():
            problems.append(f"missing-rule-candidate:{eid}@{ver}")
    for (eid, ver) in skills:
        if not (Path(root) / "skills" / "candidates" / eid / ver / "manifest.json").exists():
            problems.append(f"missing-skill-candidate:{eid}@{ver}")
    if problems:
        raise EvolutionReject("consistency", "; ".join(problems))
    return "passed", [], f"consistent: {len(rules)} rule + {len(skills)} skill versions"
