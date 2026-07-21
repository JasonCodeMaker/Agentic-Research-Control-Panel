"""Approved Project-Skill installation, canary scope, suspension, rollback (plan §12).

Installation is the only path that writes a generated Skill into `.claude/skills/`. Every
install/restore/rollback binds to an exact user approval (operation + version + digests);
suspension removes authority and is always allowed; rollback needs an exact approval unless
the active install pre-authorized a last-known-good target with no permission expansion.
"""

import os
import shutil
from pathlib import Path

from self_evolve import bundle, schema


class InstallError(Exception):
    """Reject-before-write for the deployment surface; no partial active pointer is left."""

    def __init__(self, rule, detail):
        self.rule = rule
        self.detail = detail
        super().__init__(detail)


def _bundle_files(directory):
    """All shipped files under a sealed bundle dir, keyed by relative path, except manifest.json."""
    directory = Path(directory)
    out = {}
    for p in sorted(directory.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            out[str(p.relative_to(directory))] = p.read_text(encoding="utf-8")
    return out


def approval_matches(approval, *, entity_id, entity_version, operation,
                     bundle_digest, permission_digest, now=None):
    """Exact single-purpose match (§9.6). Returns (ok, reason)."""
    if approval.get("decision") != schema.APPROVAL_DECISIONS[0]:
        return False, "not-approved"
    if approval.get("approved_by") != "user":
        return False, "not-user-approved"
    if approval.get("entity_id") != entity_id:
        return False, "entity-mismatch"
    if approval.get("entity_version") != entity_version:
        return False, "version-mismatch"
    if approval.get("operation") != operation:
        return False, "operation-mismatch"
    if approval.get("bundle_digest") != bundle_digest:
        return False, "bundle-digest-mismatch"
    if approval.get("permission_digest") != permission_digest:
        return False, "permission-digest-mismatch"
    exp = approval.get("expires_at")
    if exp and now and now > exp:
        return False, "expired"
    return True, "ok"


def _version_dirname(version, bundle_digest):
    return f"{version}-{bundle_digest.split(':')[-1][:12]}"


def _atomic_symlink(link, target):
    link.parent.mkdir(parents=True, exist_ok=True)
    tmp = link.parent / (link.name + ".tmp")
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    os.symlink(target, tmp)
    os.replace(tmp, link)  # atomic swap of the pointer


def install_skill(selfevolve_root, project_root, manifest, approval, *, now=None):
    """Atomically install an exact approved release into .claude/skills/. Returns (dest, link)."""
    eid, ver = manifest["id"], manifest["version"]
    bd = manifest["bundle_digest"]
    pd = bundle.permission_digest(manifest["permissions"])
    ok, reason = approval_matches(approval, entity_id=eid, entity_version=ver, operation="INSTALL",
                                  bundle_digest=bd, permission_digest=pd, now=now)
    if not ok:
        raise InstallError("approval-mismatch", reason)
    src = Path(selfevolve_root) / "skills" / "releases" / eid / ver
    if not src.exists():
        raise InstallError("no-release", f"no sealed release {eid}@{ver}")
    if not bundle.verify_bundle(_bundle_files(src), bd):
        raise InstallError("release-digest-mismatch", "sealed release does not match bundle_digest")
    dest = Path(project_root) / ".claude" / "skills" / ".versions" / eid / _version_dirname(ver, bd)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    if not bundle.verify_bundle(_bundle_files(dest), bd):
        shutil.rmtree(dest)
        raise InstallError("install-digest-verify-failed", "copied bundle digest mismatch")
    _atomic_symlink(Path(project_root) / ".claude" / "skills" / eid, dest)
    return dest, Path(project_root) / ".claude" / "skills" / eid


def is_invocation_allowed(state, manifest, requested_trigger):
    """Runtime gate (§12.3): deny when suspended / not deployed / outside canary scope."""
    if state == "SUSPENDED":
        return False, "suspended"
    if state not in ("CANARY", "SKILL_ACTIVE"):
        return False, f"not-deployed:{state}"
    if state == "CANARY":
        allowed = set(manifest.get("activation", {}).get("allowed_scope", []))
        if requested_trigger not in allowed:
            return False, "canary-scope-escape"
    return True, "ok"


def authorize_rollback(*, target_version, current_approval=None, pre_authorization=None,
                       manifest_permission_digest=None, target_permission_digest=None):
    """Decide if a rollback to target_version may proceed (§12.4). Returns (ok, reason).

    Automatic only under a pre-authorization that names this exact target with no permission
    expansion; otherwise a fresh exact rollback approval is required.
    """
    if target_permission_digest is not None and manifest_permission_digest is not None \
            and target_permission_digest != manifest_permission_digest:
        # rollback target widens/changes permissions relative to current → never automatic
        if pre_authorization is not None:
            return False, "permission-expansion"
    if pre_authorization is not None:
        if pre_authorization.get("rollback_to") == target_version:
            return True, "pre-authorized"
        return False, "pre-authorization-target-mismatch"
    if current_approval is not None:
        if current_approval.get("decision") == schema.APPROVAL_DECISIONS[0] \
                and current_approval.get("approved_by") == "user" \
                and current_approval.get("operation") == "ROLLBACK" \
                and current_approval.get("entity_version") == target_version:
            return True, "user-approved"
        return False, "approval-mismatch"
    return False, "no-authorization"
