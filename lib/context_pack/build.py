"""I/O loader + CLI for the Context Pack.

Reads the pipeline's existing stores (read-only) and writes two artifacts:
  outputs/<pkg>/context_pack.{md,json}   — full per-direction pack (agent working context)
  research_html/data/context-core.js     — durable, direction-independent project core
                                            (drives the human surface)

research-packages.js is read through the canonical node dumper; every other source
degrades gracefully (missing → that section is simply absent from the pack).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # lib/ on path for scope_ssot
import scope_ssot  # noqa: E402

from context_pack import assemble, render_md, render_json, is_stale  # noqa: E402

RULES_PREFIX = "window.RESEARCH_RULES = "


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_packages(root: str) -> list:
    """Read research-packages.js via the canonical node dumper. Graceful: [] on any failure."""
    root_path = Path(root)
    dump = root_path / "scripts" / "dump_packages.js"
    try:
        if dump.exists():
            out = subprocess.check_output(["node", str(dump)], text=True)
        else:
            data_file = root_path / "data" / "research-packages.js"
            if not data_file.exists():
                return []
            script = (
                "const fs = require('fs');"
                "global.window = {};"
                f"eval(fs.readFileSync({json.dumps(str(data_file))}, 'utf8'));"
                "process.stdout.write(JSON.stringify({packages: window.RESEARCH_PACKAGES || []}));"
            )
            out = subprocess.check_output(["node", "-e", script], text=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    try:
        return json.loads(out).get("packages", []) or []
    except (json.JSONDecodeError, AttributeError):
        return []


def load_rules_registry(root: str) -> list:
    """Read data/rules.js — the unified rules registry. Graceful: [] on any failure."""
    p = Path(root) / "data" / "rules.js"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8").strip()
    if not text.startswith(RULES_PREFIX):
        return []
    try:
        return json.loads(text[len(RULES_PREFIX):].rstrip(";"))
    except json.JSONDecodeError:
        return []


def load_rules_registry_strict(root: str) -> list:
    """Read data/rules.js for writer paths; malformed existing stores are not clobbered."""
    p = Path(root) / "data" / "rules.js"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8").strip()
    if not text.startswith(RULES_PREFIX):
        raise ValueError(f"Refusing to overwrite malformed rules registry: {p}")
    try:
        rows = json.loads(text[len(RULES_PREFIX):].rstrip(";"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Refusing to overwrite malformed rules registry: {p}: {e}") from e
    if not isinstance(rows, list):
        raise ValueError(f"Refusing to overwrite malformed rules registry: {p}: expected array")
    return rows


def load_learned_rules(root: str) -> list:
    """ACTIVE project-level rule texts from the registry (replaces the rules.md bullets)."""
    return [r.get("text", "") for r in load_rules_registry(root)
            if r.get("level") == "project" and r.get("status") == "ACTIVE" and r.get("text")]


def load_analysis_rules(root: str) -> list:
    """ACTIVE package lesson rows from the registry (replaces analysis.html parsing)."""
    out = []
    for r in load_rules_registry(root):
        if r.get("level") == "package" and r.get("kind") == "lesson" and r.get("status") == "ACTIVE":
            out.append({"pkg": r.get("pkg", ""), "slug": r["id"].split("#", 1)[-1],
                        "prose": r.get("text", "")})
    return out


def load_registry(root: str, name: str) -> list:
    """Read a project-level knowledge registry JSONL (papers/edges/gaps). [] if absent."""
    path = Path(root) / "data" / name
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def load_pending_triage(triage_path: str = "outputs/_scope/triage.jsonl") -> list[dict]:
    """Read latest pending Scope Triage items. Pending is advisory, never accepted intent."""
    path = Path(triage_path)
    if not path.exists():
        return []
    latest = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("id"):
            latest[rec["id"]] = rec
    return [rec for rec in latest.values() if rec.get("status") == "pending"]


def triage_version(triage_path: str = "outputs/_scope/triage.jsonl") -> int:
    """Global Triage position, used to refresh advisory pending Scope context."""
    path = Path(triage_path)
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


# Effectiveness-authority ordering for the Rule Store export (proven before advisory, §13.1).
# Keys are rule_oracle_admission canonical values (FULLY_ADMITTED before TENTATIVELY_ADMITTED).
_AUTHORITY_ORDER = {"FULLY_ADMITTED": 0, "TENTATIVELY_ADMITTED": 1}


def load_rule_store_active(selfevolve_root: str = "outputs/_selfevolve") -> list:
    """Active Rules from the self-evolve Rule Store, ordered FULLY_ADMITTED first (§13.1)."""
    from self_evolve import store as se_store  # lib/ already on path
    log = Path(selfevolve_root) / "rules" / "transitions.jsonl"
    if not log.exists():
        return []
    actives = se_store.active_transitions(se_store.read_log(log))
    rules = []
    for (eid, ver), t in actives.items():
        rel = Path(selfevolve_root) / "rules" / "releases" / eid / ver / "rule.json"
        if not rel.exists():
            continue
        rule = json.loads(rel.read_text(encoding="utf-8"))
        rules.append({"id": eid, "content": rule.get("content", ""),
                      "authority": t.get("admission", "TENTATIVELY_ADMITTED")})
    rules.sort(key=lambda r: (_AUTHORITY_ORDER.get(r["authority"], 9), r["id"]))
    return rules


def _rule_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "rule"


def _unique_rule_id(base_slug: str, source_id: str, used: set[str]) -> str:
    rid = f"PRJ-se-{base_slug}"
    if rid not in used:
        used.add(rid)
        return rid
    source_slug = re.sub(r"[^a-z0-9]+", "-", source_id.lower()).strip("-") or "rule"
    rid = f"PRJ-se-{base_slug}-{source_slug}"
    i = 2
    while rid in used:
        rid = f"PRJ-se-{base_slug}-{source_slug}-{i}"
        i += 1
    used.add(rid)
    return rid


def export_learned_rules(selfevolve_root: str, root: str) -> int:
    """Project the Rule Store's ACTIVE rules into the registry (origin=selfevolve, replace-all).

    The self-evolve store stays authoritative for the learning lifecycle; the registry
    (data/rules.js) is authoritative for what binds the agent now. This one-way export is the
    only bridge — selfevolve-origin rows are regenerated, never hand-edited. Proven-effective
    rules come first so the pack budget prunes advisory rules first.
    """
    rules = load_rule_store_active(selfevolve_root)
    registry = [r for r in load_rules_registry_strict(root) if r.get("origin") != "selfevolve"]
    used = {r.get("id") for r in registry if r.get("id")}
    for r in rules:
        rid = _unique_rule_id(_rule_slug(r["content"]), r["id"], used)
        registry.append({"id": rid, "level": "project", "kind": "constraint",
                         "title": r["content"][:60], "text": r["content"],
                         "rationale": f"self-evolve {r['authority']}",
                         "source": f"selfevolve:{r['id']}", "origin": "selfevolve",
                         "status": "ACTIVE", "addedAt": "derived"})
    p = Path(root) / "data" / "rules.js"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(RULES_PREFIX + json.dumps(registry, indent=2, ensure_ascii=False) + ";\n",
                 encoding="utf-8")
    return len(rules)


def resolve_direction(packages: list, pkg_id: str, transitions_path: str):
    """Active direction node + its scope_version for a package (None, 0 if unresolved)."""
    node_id = next((p.get("sourceDirection") for p in packages if p.get("id") == pkg_id), None)
    if not node_id:
        return None, 0
    node = scope_ssot.fold(scope_ssot.read_log(transitions_path)).get(node_id)
    if node is None:
        return None, 0
    return node, node.get("version", 0)


def _find_package(packages: list, pkg_id: str) -> dict | None:
    return next((p for p in packages if p.get("id") == pkg_id), None)


def _latest_records_by_node(records: list[dict]) -> dict[str, dict]:
    latest = {}
    for rec in records:
        latest[rec.get("node_id")] = rec
    return latest


def _package_provenance(pkg: dict | None) -> dict:
    if not pkg:
        return {}
    experiments = pkg.get("experiments") or []
    exp_tasks = sorted({
        exp.get("sourceTask")
        for exp in experiments
        if isinstance(exp, dict) and exp.get("sourceTask")
    })
    return {
        "sourceDirection": pkg.get("sourceDirection"),
        "sourceVersion": pkg.get("sourceVersion"),
        "sourceChange": pkg.get("sourceChange"),
        "sourceTasks": pkg.get("sourceTasks") or [],
        "experimentSourceTasks": exp_tasks,
    }


def _active_project_for_direction(direction_node: dict | None, projection: dict) -> dict | None:
    parent_ids = direction_node.get("parents", []) if direction_node else []
    for parent_id in parent_ids:
        node = projection.get(parent_id)
        if node and node.get("level") == "project" and node.get("status") == "ACTIVE":
            return node
    projects = scope_ssot.active_nodes(projection, "project")
    return projects[0] if projects else None


def _active_tasks_for_direction(direction_node: dict | None, projection: dict) -> list[dict]:
    if not direction_node:
        return []
    direction_id = direction_node.get("id")
    return [
        node for node in scope_ssot.active_nodes(projection, "task")
        if direction_id in (node.get("parents") or [])
    ]


def _source_task_ids(provenance: dict) -> set[str]:
    ids = set()
    for item in provenance.get("sourceTasks") or []:
        if isinstance(item, dict) and item.get("id"):
            ids.add(item["id"])
        elif isinstance(item, str):
            ids.add(item)
    return ids


def _scope_warnings(pkg: dict | None, direction_node: dict | None, task_nodes: list[dict],
                    provenance: dict, latest_records: dict[str, dict]) -> list[str]:
    warnings = []
    if not pkg:
        return [f"package {provenance.get('active_pkg', '') or 'unknown'} was not found in package registry"]
    source_direction = provenance.get("sourceDirection")
    if not source_direction:
        warnings.append("package has no sourceDirection; Scope binding cannot be verified")
    elif not direction_node:
        warnings.append(f"sourceDirection {source_direction} is missing from folded Scope")
    elif direction_node.get("status") != "ACTIVE":
        warnings.append(f"sourceDirection {source_direction} is {direction_node.get('status')}")

    latest = latest_records.get(source_direction)
    declared_version = provenance.get("sourceVersion")
    if declared_version not in (None, "", []) and latest:
        latest_version = latest.get("scope_version")
        if str(declared_version) != str(latest_version):
            warnings.append(
                f"sourceVersion {declared_version} is stale; latest Direction version is {latest_version}"
            )

    active_task_ids = {node.get("id") for node in task_nodes}
    declared_task_ids = _source_task_ids(provenance)
    if source_direction and not declared_task_ids:
        warnings.append("package has sourceDirection but no sourceTasks")
    for task_id in sorted(declared_task_ids - active_task_ids):
        warnings.append(f"sourceTasks includes {task_id}, but it is not an active Task for this Direction")
    for task_id in sorted(active_task_ids - declared_task_ids):
        warnings.append(f"active Task {task_id} is not listed in package sourceTasks")
    exp_task_ids = set(provenance.get("experimentSourceTasks") or [])
    for task_id in sorted(exp_task_ids - declared_task_ids):
        warnings.append(f"experiment sourceTask {task_id} is not listed in sourceTasks")
    return warnings


def _triage_target_id(item: dict) -> str | None:
    proposed = item.get("proposed_node") if isinstance(item.get("proposed_node"), dict) else {}
    return item.get("node_id") or proposed.get("id")


def _triage_parents(item: dict) -> list:
    proposed = item.get("proposed_node") if isinstance(item.get("proposed_node"), dict) else {}
    parents = item.get("parents") or proposed.get("parents") or []
    return parents if isinstance(parents, list) else []


def _relevant_pending_triage(pending: list[dict], project_node: dict | None,
                             direction_node: dict | None, task_nodes: list[dict]) -> list[dict]:
    project_id = project_node.get("id") if project_node else None
    direction_id = direction_node.get("id") if direction_node else None
    task_ids = {node.get("id") for node in task_nodes}
    chain = {item for item in [project_id, direction_id, *task_ids] if item}
    out = []
    for item in pending:
        target = _triage_target_id(item)
        parents = set(_triage_parents(item))
        level = item.get("level")
        if target in chain:
            out.append(item)
        elif level == "task" and direction_id and direction_id in parents:
            out.append(item)
        elif level == "direction" and target == direction_id:
            out.append(item)
        elif level == "project" and target == project_id:
            out.append(item)
    return sorted(out, key=lambda item: item.get("id", ""))


def resolve_scope_context(packages: list, pkg_id: str, transitions_path: str,
                          triage_path: str = "outputs/_scope/triage.jsonl") -> dict:
    """Resolve Project, Direction, Tasks, provenance, and freshness inputs for one package."""
    records = scope_ssot.read_log(transitions_path)
    projection = scope_ssot.fold(records)
    latest = _latest_records_by_node(records)
    pkg = _find_package(packages, pkg_id)
    provenance = _package_provenance(pkg)
    direction_id = provenance.get("sourceDirection")
    direction_node = projection.get(direction_id) if direction_id else None
    scope_version = direction_node.get("version", 0) if direction_node else 0
    project_node = _active_project_for_direction(direction_node, projection)
    task_nodes = _active_tasks_for_direction(direction_node, projection)
    pending_scope = _relevant_pending_triage(
        load_pending_triage(triage_path), project_node, direction_node, task_nodes)
    warnings = _scope_warnings(pkg, direction_node, task_nodes, provenance, latest)
    return {
        "records": records,
        "projection": projection,
        "global_scope_version": scope_ssot.global_version(records),
        "triage_version": triage_version(triage_path),
        "project_node": project_node,
        "direction_node": direction_node,
        "task_nodes": task_nodes,
        "package_provenance": provenance,
        "pending_scope": pending_scope,
        "scope_warnings": warnings,
        "scope_version": scope_version,
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build(root: str, pkg_id: str, *, transitions_path: str = "outputs/_scope/transitions.jsonl",
          triage_path: str = "outputs/_scope/triage.jsonl",
          budget_chars: int = 8000, generated_at: str | None = None,
          selfevolve_root: str | None = None):
    """Load stores → assemble full + core packs → write the three artifacts.

    When selfevolve_root is given, the registry's selfevolve-origin rows are first
    regenerated as a derived export of the Rule Store's active Rules (plan D7).
    """
    generated_at = generated_at or _now_iso()
    if selfevolve_root is not None:
        export_learned_rules(selfevolve_root, root)
    packages = load_packages(root)
    learned_rules = load_learned_rules(root)
    analysis_rules = load_analysis_rules(root)
    scope_context = resolve_scope_context(packages, pkg_id, transitions_path, triage_path=triage_path)
    direction_node = scope_context["direction_node"]
    scope_version = scope_context["scope_version"]
    global_scope_version = scope_context["global_scope_version"]
    # Project-level knowledge registries (cross-package → belong in both full + core).
    papers_registry = load_registry(root, "papers.jsonl")
    edges = load_registry(root, "edges.jsonl")
    gaps = load_registry(root, "gaps.jsonl")

    full = assemble({
        "project_node": scope_context["project_node"],
        "direction_node": direction_node,
        "task_nodes": scope_context["task_nodes"],
        "package_provenance": scope_context["package_provenance"],
        "pending_scope": scope_context["pending_scope"],
        "scope_warnings": scope_context["scope_warnings"],
        "active_pkg": pkg_id,
        "scope_version": scope_version,
        "global_scope_version": global_scope_version,
        "triage_version": scope_context["triage_version"],
        "generated_at": generated_at, "packages": packages, "learned_rules": learned_rules,
        "analysis_rules": analysis_rules,
        "papers_registry": papers_registry, "edges": edges, "gaps": gaps,
    }, budget_chars=budget_chars)

    # Durable core: direction-independent cross-package knowledge only.
    core = assemble({
        "project_node": scope_context["project_node"],
        "direction_node": None, "active_pkg": None, "scope_version": scope_version,
        "global_scope_version": global_scope_version,
        "triage_version": scope_context["triage_version"],
        "generated_at": generated_at, "packages": packages, "learned_rules": learned_rules,
        "analysis_rules": analysis_rules,
        "papers_registry": papers_registry, "edges": edges, "gaps": gaps,
    }, budget_chars=budget_chars)

    _write(Path("outputs") / pkg_id / "context_pack.md", render_md(full))
    _write(Path("outputs") / pkg_id / "context_pack.json",
           json.dumps(render_json(full), indent=2, ensure_ascii=False) + "\n")
    _write(Path(root) / "data" / "context-core.js",
           "window.RESEARCH_CONTEXT_CORE = "
           + json.dumps(render_json(core), indent=2, ensure_ascii=False) + ";\n")
    return full, core


def ensure_fresh(root: str, pkg_id: str, *, transitions_path: str = "outputs/_scope/transitions.jsonl",
                 triage_path: str = "outputs/_scope/triage.jsonl",
                 budget_chars: int = 8000, generated_at: str | None = None) -> bool:
    """Rebuild the pack iff it is missing or stale (scope advanced). Returns True if it rebuilt.

    This is the staleness + backfill contract a consumer runs before reading the pack.
    """
    pack_json = Path("outputs") / pkg_id / "context_pack.json"
    if pack_json.exists():
        try:
            pj = json.loads(pack_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pj = None
        if pj is not None:
            records = scope_ssot.read_log(transitions_path)
            if not is_stale(
                pj,
                current_global_scope_version=scope_ssot.global_version(records),
                current_triage_version=triage_version(triage_path),
            ):
                return False
    build(root, pkg_id, transitions_path=transitions_path, triage_path=triage_path,
          budget_chars=budget_chars, generated_at=generated_at)
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the Context Pack for a package.")
    ap.add_argument("--pkg", required=True)
    ap.add_argument("--root", default="research_html")
    ap.add_argument("--transitions", default="outputs/_scope/transitions.jsonl")
    ap.add_argument("--triage", default="outputs/_scope/triage.jsonl")
    ap.add_argument("--budget-chars", type=int, default=8000)
    ap.add_argument("--selfevolve-root", default=None,
                    help="regenerate the registry's selfevolve-origin rows from this Rule Store first")
    ap.add_argument("--if-stale", action="store_true",
                    help="rebuild only when the pack is missing or the scope version advanced")
    args = ap.parse_args(argv)
    if args.if_stale:
        rebuilt = ensure_fresh(args.root, args.pkg, transitions_path=args.transitions,
                               triage_path=args.triage,
                               budget_chars=args.budget_chars)
        print(f"context_pack {'rebuilt' if rebuilt else 'already fresh'} for {args.pkg}")
        return 0
    full, _ = build(args.root, args.pkg, transitions_path=args.transitions,
                    triage_path=args.triage,
                    budget_chars=args.budget_chars, selfevolve_root=args.selfevolve_root)
    print(f"context_pack → outputs/{args.pkg}/context_pack.md "
          f"({len(full.sections)} sections); core → {args.root}/data/context-core.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
