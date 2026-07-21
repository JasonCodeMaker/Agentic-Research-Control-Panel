#!/usr/bin/env python3
"""Inspect, install, initialize, migrate, and validate one ARC workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable


PIPELINE_ROOT = Path(__file__).resolve().parents[3]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from lib.interface import build_interface  # noqa: E402
from lib.research_state import (  # noqa: E402
    CURRENT_VERSION,
    EventStore,
    ResearchPaths,
    StateQuery,
    UnsupportedResearchVersion,
    UpgradeRequired,
)
from lib.research_state import migration as migration_api  # noqa: E402


PROTOCOL_FILES = ("AGENTS.md", "CLAUDE.md")
PROTOCOL_BEGIN = "<!-- ARC-PROTOCOL:BEGIN source={source} sha256={sha256} -->"
PROTOCOL_END = "<!-- ARC-PROTOCOL:END source={source} -->"
CONTENT_NOISE = frozenset(
    {
        ".git",
        ".gitignore",
        ".gitkeep",
        ".pytest_cache",
        "__pycache__",
        ".DS_Store",
        ".research",
        "AGENTS.md",
        "CLAUDE.md",
    }
)
AGENT_ROOTS = {
    "codex": Path.home() / ".agents" / "skills",
    "claude": Path.home() / ".claude" / "skills",
}


class InitBlocked(RuntimeError):
    """A setup decision or invariant prevents further mutation."""

    def __init__(self, code: str, detail: str, *, report: Any = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.report = report


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    temporary = path.parent / f".{path.name}.research-init-{uuid.uuid4().hex}"
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def resolve_paths(
    *, workspace: str | Path, research_root: str | Path | None = None
) -> ResearchPaths:
    return ResearchPaths.resolve(workspace=workspace, research_root=research_root)


def _is_external_root(paths: ResearchPaths) -> bool:
    try:
        paths.root.relative_to(paths.workspace)
    except ValueError:
        return True
    return False


def _require_workspace(paths: ResearchPaths) -> None:
    if not paths.workspace.is_dir():
        raise InitBlocked(
            "WORKSPACE_MISSING",
            f"workspace is not an existing directory: {paths.workspace}",
        )
    workspace_git_root = _git_root(paths.workspace)
    if workspace_git_root and Path(workspace_git_root).resolve() == PIPELINE_ROOT:
        raise InitBlocked(
            "TARGET_IS_TOOLBOX",
            "the ARC toolbox repository cannot be initialized as its own target workspace",
        )


def classify_arc(paths: ResearchPaths) -> dict[str, Any]:
    """Classify managed state without creating files."""
    try:
        version = paths.load_version()
    except UnsupportedResearchVersion as exc:
        return {
            "state": "INVALID",
            "version": None,
            "detail": str(exc),
            "legacy_markers": [str(path) for path in paths.legacy_markers()],
        }
    markers = paths.legacy_markers()
    if version is not None:
        return {
            "state": "CURRENT",
            "version": version,
            "detail": None,
            "legacy_markers": [str(path) for path in markers],
        }
    migration_manifest = paths.state / "migration.json"
    if migration_manifest.is_file():
        return {
            "state": "MIGRATION_STAGED",
            "version": None,
            "detail": "an explicit migration exists but VERSION is not finalized",
            "legacy_markers": [str(path) for path in markers],
        }
    if paths.root.exists() and any(paths.root.iterdir()):
        return {
            "state": "INVALID",
            "version": None,
            "detail": f"unversioned research root contains data: {paths.root}",
            "legacy_markers": [str(path) for path in markers],
        }
    if markers:
        return {
            "state": "LEGACY",
            "version": None,
            "detail": "legacy ARC-managed roots require explicit migration",
            "legacy_markers": [str(path) for path in markers],
        }
    return {
        "state": "ABSENT",
        "version": None,
        "detail": None,
        "legacy_markers": [],
    }


def project_content_state(paths: ResearchPaths) -> dict[str, Any]:
    content: list[str] = []
    for entry in paths.workspace.iterdir():
        if entry.name in CONTENT_NOISE:
            continue
        try:
            if entry.resolve() == paths.root:
                continue
        except OSError:
            pass
        content.append(entry.name)
    return {"state": "EXISTING" if content else "EMPTY", "entries": sorted(content)}


def _git_root(workspace: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _protocol_source(name: str) -> tuple[str, str]:
    source = PIPELINE_ROOT / name
    if not source.is_file():
        raise InitBlocked("PROTOCOL_SOURCE_MISSING", f"missing toolbox protocol: {source}")
    text = source.read_text(encoding="utf-8").rstrip() + "\n"
    return text, _sha256(text)


def _protocol_block(name: str, source: str, digest: str) -> str:
    return (
        PROTOCOL_BEGIN.format(source=name, sha256=digest)
        + "\n"
        + source.rstrip()
        + "\n"
        + PROTOCOL_END.format(source=name)
        + "\n"
    )


def protocol_status(workspace: Path, name: str) -> dict[str, Any]:
    target = workspace / name
    source, digest = _protocol_source(name)
    base = {"path": str(target), "source_sha256": digest}
    if target.is_symlink():
        return {**base, "status": "CONFLICT", "detail": "protocol path is a symlink"}
    if not target.exists():
        return {**base, "status": "MISSING", "detail": None}
    if not target.is_file():
        return {**base, "status": "CONFLICT", "detail": "protocol path is not a file"}
    existing = target.read_text(encoding="utf-8")
    begin_pattern = re.escape("<!-- ARC-PROTOCOL:BEGIN source=" + name + " sha256=")
    end_marker = PROTOCOL_END.format(source=name)
    pattern = re.compile(
        begin_pattern
        + r"(?P<sha256>[0-9a-f]{64}) -->\n(?P<body>.*?)\n"
        + re.escape(end_marker),
        re.DOTALL,
    )
    matches = list(pattern.finditer(existing))
    has_marker = "ARC-PROTOCOL:BEGIN" in existing or "ARC-PROTOCOL:END" in existing
    if len(matches) > 1:
        return {
            **base,
            "status": "CONFLICT",
            "detail": "multiple managed protocol blocks exist",
        }
    if matches:
        match = matches[0]
        actual_body = match.group("body").rstrip() + "\n"
        if match.group("sha256") == digest and actual_body == source:
            status = "CURRENT"
        else:
            status = "STALE"
        return {
            **base,
            "status": status,
            "managed_sha256": match.group("sha256"),
            "detail": None,
        }
    if has_marker:
        return {**base, "status": "CONFLICT", "detail": "managed protocol markers are malformed"}
    if existing.strip() == source.strip():
        return {**base, "status": "LEGACY_EXACT", "detail": None}
    return {
        **base,
        "status": "UNMANAGED",
        "detail": "existing user-owned file needs an explicit managed-block merge",
    }


def protocol_inventory(workspace: Path) -> dict[str, dict[str, Any]]:
    return {name: protocol_status(workspace, name) for name in PROTOCOL_FILES}


def _preflight_protocols(workspace: Path, *, merge_unmanaged: bool) -> None:
    inventory = protocol_inventory(workspace)
    conflicts = {
        name: row
        for name, row in inventory.items()
        if row["status"] == "CONFLICT"
        or (row["status"] == "UNMANAGED" and not merge_unmanaged)
    }
    if conflicts:
        raise InitBlocked(
            "PROTOCOL_REVIEW_REQUIRED",
            "existing protocol files require review; rerun with --merge-protocols after inspecting the diff",
            report=conflicts,
        )


def attach_protocols(workspace: Path, *, merge_unmanaged: bool) -> dict[str, str]:
    _preflight_protocols(workspace, merge_unmanaged=merge_unmanaged)
    actions: dict[str, str] = {}
    for name in PROTOCOL_FILES:
        target = workspace / name
        source, digest = _protocol_source(name)
        block = _protocol_block(name, source, digest)
        row = protocol_status(workspace, name)
        status = row["status"]
        if status == "CURRENT":
            actions[name] = "unchanged"
            continue
        if status in {"MISSING", "LEGACY_EXACT"}:
            _write_text_atomic(target, block)
            actions[name] = "created" if status == "MISSING" else "adopted"
            continue
        existing = target.read_text(encoding="utf-8")
        if status == "STALE":
            pattern = re.compile(
                re.escape("<!-- ARC-PROTOCOL:BEGIN source=" + name + " sha256=")
                + r"[0-9a-f]{64} -->\n.*?\n"
                + re.escape(PROTOCOL_END.format(source=name))
                + r"\n?",
                re.DOTALL,
            )
            updated, replacements = pattern.subn(block, existing, count=1)
            if replacements != 1:
                raise InitBlocked("PROTOCOL_REPLACE_FAILED", f"could not update {target}")
            _write_text_atomic(target, updated.rstrip() + "\n")
            actions[name] = "updated"
            continue
        if status == "UNMANAGED" and merge_unmanaged:
            updated = existing.rstrip() + "\n\n" + block
            _write_text_atomic(target, updated)
            actions[name] = "merged"
            continue
        raise InitBlocked("PROTOCOL_APPLY_FAILED", f"unsupported protocol state for {name}: {status}")
    return actions


def _agent_names(agent: str) -> tuple[str, ...]:
    return ("codex", "claude") if agent == "both" else (agent,)


def _skill_roots(
    *,
    agent: str,
    codex_root: str | Path | None = None,
    claude_root: str | Path | None = None,
) -> dict[str, Path]:
    overrides = {"codex": codex_root, "claude": claude_root}
    return {
        name: Path(overrides[name]).expanduser().resolve()
        if overrides[name] is not None
        else AGENT_ROOTS[name].expanduser().resolve()
        for name in _agent_names(agent)
    }


def _source_skills() -> dict[str, Path]:
    skills: dict[str, Path] = {}
    for directory in sorted((PIPELINE_ROOT / "skills").iterdir()):
        skill_file = directory / "SKILL.md"
        if not directory.is_dir() or not skill_file.is_file():
            continue
        match = re.search(
            r"^name:\s*[\"']?([^\"'\s]+)[\"']?\s*$",
            skill_file.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if not match or match.group(1) != directory.name:
            raise InitBlocked(
                "SKILL_FRONTMATTER_INVALID",
                f"{skill_file} must declare name: {directory.name}",
            )
        skills[directory.name] = directory.resolve()
    if "research-init" not in skills:
        raise InitBlocked("SKILL_SOURCE_MISSING", "research-init is absent from the toolbox skill tree")
    return skills


def _skill_link_status(destination: Path, source: Path) -> str:
    if destination.is_symlink():
        return "CURRENT" if destination.resolve(strict=False) == source else "WRONG_LINK"
    if os.path.lexists(destination):
        return "CONFLICT"
    return "MISSING"


def skill_inventory(
    *,
    agent: str,
    codex_root: str | Path | None = None,
    claude_root: str | Path | None = None,
) -> dict[str, Any]:
    sources = _source_skills()
    output: dict[str, Any] = {}
    for name, root in _skill_roots(
        agent=agent, codex_root=codex_root, claude_root=claude_root
    ).items():
        output[name] = {
            "root": str(root),
            "skills": {
                skill: {
                    "status": _skill_link_status(root / skill, source),
                    "source": str(source),
                    "destination": str(root / skill),
                }
                for skill, source in sources.items()
            },
        }
    return output


def _preflight_skill_links(inventory: dict[str, Any]) -> None:
    conflicts: list[str] = []
    for agent, agent_row in inventory.items():
        for skill, row in agent_row["skills"].items():
            if row["status"] == "CONFLICT":
                conflicts.append(f"{agent}:{skill}:{row['destination']}")
    if conflicts:
        raise InitBlocked(
            "SKILL_PATH_CONFLICT",
            "user-owned skill paths cannot be replaced automatically: " + ", ".join(conflicts),
            report=conflicts,
        )


def install_skill_links(
    *,
    agent: str,
    codex_root: str | Path | None = None,
    claude_root: str | Path | None = None,
) -> dict[str, Any]:
    sources = _source_skills()
    inventory = skill_inventory(
        agent=agent, codex_root=codex_root, claude_root=claude_root
    )
    _preflight_skill_links(inventory)
    actions: dict[str, Any] = {}
    for agent_name, root in _skill_roots(
        agent=agent, codex_root=codex_root, claude_root=claude_root
    ).items():
        root.mkdir(parents=True, exist_ok=True)
        actions[agent_name] = {"root": str(root), "skills": {}}
        for skill, source in sources.items():
            destination = root / skill
            status = _skill_link_status(destination, source)
            if status == "CURRENT":
                actions[agent_name]["skills"][skill] = "unchanged"
                continue
            temporary = root / f".{skill}.research-init-{uuid.uuid4().hex}"
            try:
                temporary.symlink_to(source, target_is_directory=True)
                os.replace(temporary, destination)
            finally:
                if temporary.exists() or temporary.is_symlink():
                    temporary.unlink()
            actions[agent_name]["skills"][skill] = (
                "created" if status == "MISSING" else "repaired"
            )
    return actions


def _run_json(command: list[str]) -> tuple[int, dict[str, Any], str]:
    result = subprocess.run(
        command,
        cwd=str(PIPELINE_ROOT),
        capture_output=True,
        text=True,
    )
    payload: dict[str, Any] = {}
    for line in reversed([line for line in result.stdout.splitlines() if line.strip()]):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    return result.returncode, payload, result.stderr.strip()


def dashboard_status(paths: ResearchPaths) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "lib.interface.serve",
        "--workspace",
        str(paths.workspace),
        "--research-root",
        str(paths.root),
        "status",
        "--json",
    ]
    _, payload, stderr = _run_json(command)
    if not payload:
        payload = {"ok": False, "status": "unknown", "error": stderr or "no status payload"}
    return payload


def ensure_dashboard_server(
    paths: ResearchPaths,
    *,
    host: str = "127.0.0.1",
    port: int = 8904,
    max_port: int = 8999,
) -> dict[str, Any]:
    before = dashboard_status(paths)
    command = [
        sys.executable,
        "-m",
        "lib.interface.serve",
        "--workspace",
        str(paths.workspace),
        "--research-root",
        str(paths.root),
        "ensure",
        "--host",
        host,
        "--port",
        str(port),
        "--max-port",
        str(max_port),
        "--json",
    ]
    returncode, payload, stderr = _run_json(command)
    if returncode != 0 or not payload.get("ok"):
        raise InitBlocked(
            "DASHBOARD_SERVER_FAILED",
            str(payload.get("error") or stderr or "dashboard server failed"),
            report=payload,
        )
    action = "reused" if before.get("ok") and before.get("pid") == payload.get("pid") else "started"
    actual_host = str(payload.get("host") or host)
    actual_port = int(payload.get("port") or port)
    return {
        **payload,
        "action": action,
        "health": "healthy",
        "remote_access": f"ssh -L {actual_port}:{actual_host}:{actual_port} <host>",
        "stop_command": shlex.join(
            [
                sys.executable,
                "-m",
                "lib.interface.serve",
                "--workspace",
                str(paths.workspace),
                "--research-root",
                str(paths.root),
                "stop",
                "--json",
            ]
        ),
    }


def _has_project(paths: ResearchPaths) -> bool:
    projects = StateQuery(paths).show("project")["data"]
    return any(
        isinstance(project, dict)
        and project.get("level") == "project"
        and project.get("status") == "ACTIVE"
        for project in projects.values()
    )


def _next_action(arc_state: str, has_project: bool | None) -> str:
    if arc_state == "LEGACY":
        return "review inventory, confirm a recoverable backup, then run research-init migrate"
    if arc_state == "MIGRATION_STAGED":
        return "resume research-init migrate or inspect migration check blockers"
    if arc_state == "INVALID":
        return "repair the version or unversioned research-root conflict"
    if arc_state == "ABSENT":
        return "run research-init setup"
    return "use research-brainstorm or research-scope" if has_project else "use research-onboard"


def inspect_workspace(
    paths: ResearchPaths,
    *,
    agent: str,
    codex_root: str | Path | None = None,
    claude_root: str | Path | None = None,
) -> dict[str, Any]:
    _require_workspace(paths)
    arc = classify_arc(paths)
    has_project: bool | None = None
    state_check: dict[str, Any] = {"ok": False, "status": "not-ready"}
    server: dict[str, Any] = {"ok": False, "status": "not-applicable"}
    if arc["state"] == "CURRENT":
        try:
            state = EventStore(paths).state()
            has_project = _has_project(paths)
            state_check = {
                "ok": True,
                "source_seq": state.get("source_seq"),
                "source_hash": state.get("source_hash"),
            }
            server = dashboard_status(paths)
        except Exception as exc:
            state_check = {"ok": False, "status": "invalid", "detail": str(exc)}
    protocols = protocol_inventory(paths.workspace)
    skill_links = skill_inventory(
        agent=agent, codex_root=codex_root, claude_root=claude_root
    )
    interface = {
        "root": str(paths.interface),
        "exists": paths.interface.is_dir(),
        "index_exists": (paths.interface / "index.html").is_file(),
    }
    setup_ready = (
        arc["state"] == "CURRENT"
        and bool(state_check.get("ok"))
        and all(row["status"] == "CURRENT" for row in protocols.values())
        and all(
            row["status"] == "CURRENT"
            for agent_row in skill_links.values()
            for row in agent_row["skills"].values()
        )
        and interface["index_exists"]
        and bool(server.get("ok"))
    )
    return {
        "ok": True,
        "action": "inspect",
        "pipeline_root": str(PIPELINE_ROOT),
        "workspace": str(paths.workspace),
        "workspace_git_root": _git_root(paths.workspace),
        "research_root": str(paths.root),
        "research_root_external": _is_external_root(paths),
        "arc": arc,
        "project_content": project_content_state(paths),
        "protocols": protocols,
        "skill_links": skill_links,
        "state_check": state_check,
        "interface": interface,
        "server": server,
        "has_project": has_project,
        "setup_ready": setup_ready,
        "next_action": (
            _next_action(arc["state"], has_project)
            if arc["state"] != "CURRENT" or setup_ready
            else "run research-init setup to reconcile the reported setup gaps"
        ),
    }


def _require_external_root_permission(paths: ResearchPaths, allowed: bool) -> None:
    if _is_external_root(paths) and not allowed:
        raise InitBlocked(
            "EXTERNAL_RESEARCH_ROOT_REQUIRES_CONFIRMATION",
            f"research root is outside the workspace: {paths.root}; rerun with --allow-external-research-root",
        )


def _preflight_apply(
    paths: ResearchPaths,
    *,
    agent: str,
    merge_protocols: bool,
    skip_skill_install: bool,
    codex_root: str | Path | None,
    claude_root: str | Path | None,
) -> None:
    _require_workspace(paths)
    _preflight_protocols(paths.workspace, merge_unmanaged=merge_protocols)
    if not skip_skill_install:
        _preflight_skill_links(
            skill_inventory(
                agent=agent, codex_root=codex_root, claude_root=claude_root
            )
        )


def _apply_common(
    paths: ResearchPaths,
    *,
    agent: str,
    merge_protocols: bool,
    skip_skill_install: bool,
    no_serve: bool,
    host: str,
    port: int,
    max_port: int,
    codex_root: str | Path | None,
    claude_root: str | Path | None,
) -> dict[str, Any]:
    skills = (
        {"status": "skipped-by-user"}
        if skip_skill_install
        else install_skill_links(
            agent=agent, codex_root=codex_root, claude_root=claude_root
        )
    )
    protocols = attach_protocols(paths.workspace, merge_unmanaged=merge_protocols)
    if no_serve:
        build = build_interface(paths)
        server = {
            "ok": False,
            "status": "disabled-by-user",
            "action": "not-started",
            "health": "not-checked",
            "interface_root": str(build.root),
            "files_written": len(build.files),
        }
    else:
        try:
            server = ensure_dashboard_server(
                paths, host=host, port=port, max_port=max_port
            )
        except InitBlocked as exc:
            server = {
                "ok": False,
                "status": "error",
                "action": "failed",
                "health": "unhealthy",
                "error": exc.code,
                "detail": exc.detail,
                "report": exc.report,
            }
    has_project = _has_project(paths)
    ready = no_serve or bool(server.get("ok"))
    return {
        "ok": ready,
        "skills": skills,
        "protocols": protocols,
        "server": server,
        "has_project": has_project,
        "setup_status": (
            "READY_WITH_PROJECT"
            if ready and has_project
            else "READY_NO_PROJECT"
            if ready
            else "REPAIR_REQUIRED"
        ),
        "next_action": (
            _next_action("CURRENT", has_project)
            if ready
            else "repair the Dashboard Server, then run research-init check"
        ),
    }


def setup_workspace(
    paths: ResearchPaths,
    *,
    agent: str,
    merge_protocols: bool,
    skip_skill_install: bool,
    no_serve: bool,
    allow_external_research_root: bool,
    host: str,
    port: int,
    max_port: int,
    codex_root: str | Path | None = None,
    claude_root: str | Path | None = None,
) -> dict[str, Any]:
    _require_external_root_permission(paths, allow_external_research_root)
    _preflight_apply(
        paths,
        agent=agent,
        merge_protocols=merge_protocols,
        skip_skill_install=skip_skill_install,
        codex_root=codex_root,
        claude_root=claude_root,
    )
    arc = classify_arc(paths)
    if arc["state"] in {"LEGACY", "MIGRATION_STAGED"}:
        raise InitBlocked(
            "MIGRATION_REQUIRED",
            "legacy or staged state requires research-init migrate after backup review",
            report=arc,
        )
    if arc["state"] == "INVALID":
        raise InitBlocked("INVALID_RESEARCH_ROOT", str(arc["detail"]), report=arc)
    created: list[str] = []
    if arc["state"] == "ABSENT":
        created = [str(path) for path in EventStore(paths).initialize()]
    common = _apply_common(
        paths,
        agent=agent,
        merge_protocols=merge_protocols,
        skip_skill_install=skip_skill_install,
        no_serve=no_serve,
        host=host,
        port=port,
        max_port=max_port,
        codex_root=codex_root,
        claude_root=claude_root,
    )
    return {
        "ok": True,
        "action": "setup",
        "workspace": str(paths.workspace),
        "research_root": str(paths.root),
        "arc_before": arc["state"],
        "version": paths.load_version(),
        "created": created,
        **common,
    }


def migrate_workspace(
    paths: ResearchPaths,
    *,
    backup_confirmed: bool,
    agent: str,
    merge_protocols: bool,
    skip_skill_install: bool,
    no_serve: bool,
    allow_external_research_root: bool,
    host: str,
    port: int,
    max_port: int,
    codex_root: str | Path | None = None,
    claude_root: str | Path | None = None,
) -> dict[str, Any]:
    _require_external_root_permission(paths, allow_external_research_root)
    _preflight_apply(
        paths,
        agent=agent,
        merge_protocols=merge_protocols,
        skip_skill_install=skip_skill_install,
        codex_root=codex_root,
        claude_root=claude_root,
    )
    arc = classify_arc(paths)
    if arc["state"] == "ABSENT":
        raise InitBlocked("NO_LEGACY_STATE", "no legacy ARC state exists; use research-init setup")
    if arc["state"] == "INVALID":
        raise InitBlocked("INVALID_RESEARCH_ROOT", str(arc["detail"]), report=arc)
    if arc["state"] in {"LEGACY", "MIGRATION_STAGED"} and not backup_confirmed:
        inventory = migration_api.inventory(paths.workspace, paths=paths)
        raise InitBlocked(
            "BACKUP_CONFIRMATION_REQUIRED",
            "review inventory and confirm a recoverable backup before migration",
            report=inventory,
        )
    if arc["state"] == "CURRENT" and not (paths.state / "migration.json").is_file():
        raise InitBlocked("NO_MIGRATION_MANIFEST", "current workspace was not created by legacy migration")
    inventory = migration_api.inventory(paths.workspace, paths=paths)
    migration = migration_api.migrate(paths)
    check = migration_api.check(paths)
    if not migration.get("ok") or not check.get("ok"):
        raise InitBlocked(
            "MIGRATION_BLOCKED",
            "legacy migration did not pass every parity and evidence gate",
            report={"inventory": inventory, "migration": migration, "check": check},
        )
    common = _apply_common(
        paths,
        agent=agent,
        merge_protocols=merge_protocols,
        skip_skill_install=skip_skill_install,
        no_serve=no_serve,
        host=host,
        port=port,
        max_port=max_port,
        codex_root=codex_root,
        claude_root=claude_root,
    )
    return {
        "ok": True,
        "action": "migrate",
        "workspace": str(paths.workspace),
        "research_root": str(paths.root),
        "arc_before": arc["state"],
        "version": paths.load_version(),
        "inventory": inventory,
        "migration": migration,
        "check": check,
        **common,
    }


def check_workspace(
    paths: ResearchPaths,
    *,
    agent: str,
    require_server: bool,
    codex_root: str | Path | None = None,
    claude_root: str | Path | None = None,
) -> dict[str, Any]:
    _require_workspace(paths)
    arc = classify_arc(paths)
    failures: list[dict[str, Any]] = []
    state: dict[str, Any] | None = None
    if arc["state"] != "CURRENT":
        failures.append({"code": "STATE_NOT_CURRENT", "detail": arc})
    else:
        try:
            state = EventStore(paths).state()
        except Exception as exc:
            failures.append({"code": "STATE_CHECK_FAILED", "detail": str(exc)})
    protocols = protocol_inventory(paths.workspace)
    for name, row in protocols.items():
        if row["status"] != "CURRENT":
            failures.append({"code": "PROTOCOL_NOT_CURRENT", "file": name, "detail": row})
    skills = skill_inventory(
        agent=agent, codex_root=codex_root, claude_root=claude_root
    )
    for agent_name, agent_row in skills.items():
        for skill, row in agent_row["skills"].items():
            if row["status"] != "CURRENT":
                failures.append(
                    {
                        "code": "SKILL_NOT_CURRENT",
                        "agent": agent_name,
                        "skill": skill,
                        "detail": row,
                    }
                )
    interface = {
        "root": str(paths.interface),
        "index_exists": (paths.interface / "index.html").is_file(),
    }
    if not interface["index_exists"]:
        failures.append({"code": "INTERFACE_MISSING", "detail": interface})
    server = dashboard_status(paths) if arc["state"] == "CURRENT" else {"ok": False}
    if require_server and not server.get("ok"):
        failures.append({"code": "DASHBOARD_SERVER_UNHEALTHY", "detail": server})
    migration_check: dict[str, Any] | None = None
    if (paths.state / "migration.json").is_file():
        migration_check = migration_api.check(paths)
        if not migration_check.get("ok"):
            failures.append({"code": "MIGRATION_CHECK_FAILED", "detail": migration_check})
    has_project = _has_project(paths) if state is not None else None
    return {
        "ok": not failures,
        "action": "check",
        "workspace": str(paths.workspace),
        "research_root": str(paths.root),
        "version": arc.get("version"),
        "arc": arc,
        "state": {
            "ok": state is not None,
            "source_seq": state.get("source_seq") if state else None,
            "source_hash": state.get("source_hash") if state else None,
        },
        "protocols": protocols,
        "skill_links": skills,
        "interface": interface,
        "server": server,
        "migration": migration_check,
        "has_project": has_project,
        "setup_status": (
            "READY_WITH_PROJECT"
            if not failures and has_project
            else "READY_NO_PROJECT"
            if not failures
            else "REPAIR_REQUIRED"
        ),
        "next_action": (
            _next_action(arc["state"], has_project)
            if not failures
            else "repair the reported setup invariants, then run research-init check"
        ),
        "failures": failures,
    }


def _common_apply_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent", choices=("codex", "claude", "both"), default="codex")
    parser.add_argument("--merge-protocols", action="store_true")
    parser.add_argument("--skip-skill-install", action="store_true")
    parser.add_argument("--no-serve", action="store_true")
    parser.add_argument("--allow-external-research-root", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8904)
    parser.add_argument("--max-port", type=int, default=8999)
    parser.add_argument("--codex-skills-root")
    parser.add_argument("--claude-skills-root")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="read-only setup classification")
    inspect.add_argument("--agent", choices=("codex", "claude", "both"), default="codex")
    inspect.add_argument("--codex-skills-root")
    inspect.add_argument("--claude-skills-root")

    setup = sub.add_parser("setup", help="initialize or reconcile a non-legacy workspace")
    _common_apply_arguments(setup)

    migrate = sub.add_parser("migrate", help="explicitly migrate a legacy workspace")
    _common_apply_arguments(migrate)
    migrate.add_argument("--backup-confirmed", action="store_true")

    check = sub.add_parser("check", help="validate setup without repairing it")
    check.add_argument("--agent", choices=("codex", "claude", "both"), default="codex")
    check.add_argument("--allow-no-server", action="store_true")
    check.add_argument("--codex-skills-root")
    check.add_argument("--claude-skills-root")

    install = sub.add_parser("install-skills", help="install or repair skill symlinks")
    install.add_argument("--agent", choices=("codex", "claude", "both"), default="codex")
    install.add_argument("--codex-skills-root")
    install.add_argument("--claude-skills-root")
    return parser


def _paths_from_args(args: argparse.Namespace) -> ResearchPaths:
    return resolve_paths(workspace=args.workspace, research_root=args.research_root)


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "install-skills":
            payload = {
                "ok": True,
                "action": "install-skills",
                "skill_links": install_skill_links(
                    agent=args.agent,
                    codex_root=args.codex_skills_root,
                    claude_root=args.claude_skills_root,
                ),
            }
        else:
            paths = _paths_from_args(args)
            if args.command == "inspect":
                payload = inspect_workspace(
                    paths,
                    agent=args.agent,
                    codex_root=args.codex_skills_root,
                    claude_root=args.claude_skills_root,
                )
            elif args.command == "setup":
                payload = setup_workspace(
                    paths,
                    agent=args.agent,
                    merge_protocols=args.merge_protocols,
                    skip_skill_install=args.skip_skill_install,
                    no_serve=args.no_serve,
                    allow_external_research_root=args.allow_external_research_root,
                    host=args.host,
                    port=args.port,
                    max_port=args.max_port,
                    codex_root=args.codex_skills_root,
                    claude_root=args.claude_skills_root,
                )
            elif args.command == "migrate":
                payload = migrate_workspace(
                    paths,
                    backup_confirmed=args.backup_confirmed,
                    agent=args.agent,
                    merge_protocols=args.merge_protocols,
                    skip_skill_install=args.skip_skill_install,
                    no_serve=args.no_serve,
                    allow_external_research_root=args.allow_external_research_root,
                    host=args.host,
                    port=args.port,
                    max_port=args.max_port,
                    codex_root=args.codex_skills_root,
                    claude_root=args.claude_skills_root,
                )
            else:
                payload = check_workspace(
                    paths,
                    agent=args.agent,
                    require_server=not args.allow_no_server,
                    codex_root=args.codex_skills_root,
                    claude_root=args.claude_skills_root,
                )
        print(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if payload.get("ok", False) else 2
    except (InitBlocked, UnsupportedResearchVersion, UpgradeRequired, migration_api.MigrationError) as exc:
        payload = {
            "ok": False,
            "action": args.command,
            "error": getattr(exc, "code", type(exc).__name__),
            "detail": getattr(exc, "detail", str(exc)),
        }
        report = getattr(exc, "report", None)
        if report is not None:
            payload["report"] = report
        print(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
