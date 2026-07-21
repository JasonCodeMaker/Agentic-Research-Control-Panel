"""State-backed Context Pack query.

The management event log is the only input.  The result exists only in memory
unless an experiment launcher freezes it into that Run's immutable
``context.json``.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

LIB_ROOT = Path(__file__).resolve().parents[1]
if str(LIB_ROOT) not in sys.path:
    sys.path.insert(0, str(LIB_ROOT))

try:  # package import
    from . import assemble, render_json, render_md
except ImportError:  # direct ``python lib/context_pack/build.py``
    from context_pack import assemble, render_json, render_md  # type: ignore

try:  # ``lib.context_pack.build``
    from ..research_state import EventStore, ResearchPaths, UpgradeRequired
    from ..research_state.migration_facts import legacy_package_fact_projection
except ImportError:  # top-level ``context_pack.build`` / direct script
    from research_state import EventStore, ResearchPaths, UpgradeRequired  # type: ignore
    from research_state.migration_facts import (  # type: ignore
        legacy_package_fact_projection,
    )


def _paths(
    workspace_or_paths: str | Path | ResearchPaths = ".",
    *,
    research_root: str | Path | None = None,
) -> ResearchPaths:
    # ``lib.research_state`` and ``research_state`` can both be importable in
    # local skill/test entrypoints.  Accept the resolver by protocol as well as
    # exact class identity so a valid ResearchPaths is never coerced to Path.
    if isinstance(workspace_or_paths, ResearchPaths) or (
        hasattr(workspace_or_paths, "workspace")
        and hasattr(workspace_or_paths, "root")
        and hasattr(workspace_or_paths, "events")
        and hasattr(workspace_or_paths, "current")
    ):
        if research_root is not None:
            raise ValueError("research_root cannot accompany an existing ResearchPaths")
        return workspace_or_paths

    workspace = Path(workspace_or_paths).expanduser().resolve()
    if workspace.name == ".research" or (workspace / "VERSION").is_file():
        return ResearchPaths.resolve(
            workspace=workspace.parent,
            research_root=workspace,
        )
    return ResearchPaths.resolve(workspace=workspace, research_root=research_root)


def _management_state(paths: ResearchPaths) -> dict[str, Any]:
    version = paths.load_version()
    if version is None:
        markers = paths.legacy_markers()
        if markers:
            raise UpgradeRequired(
                "upgrade-required: Context Pack queries require migrated research state; "
                f"legacy stores remain at {', '.join(str(path) for path in markers)}"
            )
        raise UpgradeRequired(
            f"research state is not initialized at {paths.root}; initialize or migrate it first"
        )
    return EventStore(paths).state()


def _records(state: dict[str, Any], aggregate_type: str) -> list[dict[str, Any]]:
    bucket = state["aggregates"].get(aggregate_type, {})
    return [
        copy.deepcopy(record)
        for _, record in sorted(bucket.items())
        if isinstance(record, dict)
    ]


def _direction_id(package: dict[str, Any]) -> str | None:
    value = package.get("direction_id") or package.get("sourceDirection")
    return str(value) if value else None


def _project_for_direction(
    projects: list[dict[str, Any]],
    direction: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if direction:
        project_id = direction.get("project_id")
        parents = direction.get("parents") or []
        candidates = [project_id, *parents]
        for candidate in candidates:
            if candidate:
                match = next(
                    (row for row in projects if row.get("id") == candidate),
                    None,
                )
                if match is not None:
                    return match
    active = [
        row
        for row in projects
        if row.get("status", "ACTIVE") == "ACTIVE"
    ]
    return active[0] if active else (projects[0] if projects else None)


def _package_experiments(
    experiments: list[dict[str, Any]],
    package: dict[str, Any],
    _direction_id: str | None,
) -> list[dict[str, Any]]:
    """Select only Experiments owned by this Package.

    Direction membership alone is insufficient because one Direction may own
    several Packages and still have unmaterialized Scope Experiments.
    """
    return [
        experiment
        for experiment in experiments
        if experiment.get("package_id") == package.get("id")
    ]


def _packages_with_results(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Project finalized Run results into package context without a second writer."""
    packages = _records(state, "package")
    package_index = {
        str(package.get("id")): package
        for package in packages
        if package.get("id")
    }
    experiments = {
        str(identity): record
        for identity, record in state["aggregates"]["experiment"].items()
        if isinstance(record, dict)
    }
    derived: dict[str, list[dict[str, Any]]] = {}
    for run_id, run in sorted(state["aggregates"]["run"].items()):
        if not isinstance(run, dict):
            continue
        package_id = str(run.get("package_id") or "")
        result = run.get("latest_scientific_result")
        experiment = experiments.get(str(run.get("experiment_id") or ""))
        if (
            package_id not in package_index
            or not isinstance(result, dict)
            or not isinstance(experiment, dict)
        ):
            continue
        spec = experiment.get("spec")
        spec = spec if isinstance(spec, dict) else {}
        measurements = result.get("measurements")
        measurements = measurements if isinstance(measurements, dict) else {}
        metric = str(result.get("metric") or "")
        measured = copy.deepcopy(result.get("measured"))
        if not metric and len(measurements) == 1:
            metric, measured = next(iter(measurements.items()))
            metric = str(metric)
        elif measured is None:
            measured = copy.deepcopy(measurements) if measurements else "unmeasured"
        local_id = str(
            result.get("experiment_local_id")
            or run.get("experiment_local_id")
            or experiment.get("local_id")
            or experiment.get("id")
            or ""
        )
        evidence = result.get("evidence")
        evidence = evidence if isinstance(evidence, list) else []
        evidence_path = next(
            (
                str(ref.get("uri"))
                for ref in evidence
                if isinstance(ref, dict) and ref.get("uri")
            ),
            str(result.get("result_json") or ""),
        )
        derived.setdefault(package_id, []).append(
            {
                "id": f"{local_id}::{run_id}",
                "run_id": str(run_id),
                "exp_id": local_id,
                "method": result.get("method")
                or spec.get("purpose")
                or local_id,
                "hypothesis": result.get("hypothesis") or "",
                "gate": result.get("gate") or spec.get("gate") or "",
                "metric": metric,
                "measured": measured,
                "verdict": result.get("verdict"),
                "validity": result.get("validity"),
                "evidence": copy.deepcopy(evidence),
                "evidencePath": evidence_path,
            }
        )
    for package_id, package in package_index.items():
        rows = derived.get(package_id, [])
        legacy_rows = legacy_package_fact_projection(package)["methodsTried"]
        existing = (
            copy.deepcopy(legacy_rows)
            if legacy_rows
            else
            [
                copy.deepcopy(row)
                for row in package.get("methodsTried", [])
                if isinstance(row, dict)
            ]
            if isinstance(package.get("methodsTried"), list)
            else []
        )
        if not existing and not rows:
            continue
        by_id = {
            str(row.get("id") or row.get("run_id")): index
            for index, row in enumerate(existing)
            if row.get("id") or row.get("run_id")
        }
        for row in rows:
            identity = str(row["id"])
            if identity in by_id:
                existing[by_id[identity]] = row
            else:
                by_id[identity] = len(existing)
                existing.append(row)
        package["methodsTried"] = existing
    return packages


def _package_provenance(
    package: dict[str, Any],
    experiments: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "sourceDirection": _direction_id(package),
        "sourceVersion": package.get("sourceVersion"),
        "sourceChange": package.get("sourceChange"),
        "sourceExperiments": copy.deepcopy(
            package.get("sourceExperiments") or []
        ),
    }


def _target_id(proposal: dict[str, Any]) -> str | None:
    proposed = (
        proposal.get("proposed_node")
        if isinstance(proposal.get("proposed_node"), dict)
        else {}
    )
    value = (
        proposal.get("aggregate_id")
        or proposal.get("node_id")
        or proposed.get("id")
    )
    return str(value) if value else None


def _pending_proposals(
    proposals: list[dict[str, Any]],
    *,
    package_id: str,
    project_id: str | None,
    direction_id: str | None,
    experiment_ids: set[str],
) -> list[dict[str, Any]]:
    chain = {
        value
        for value in {package_id, project_id, direction_id, *experiment_ids}
        if value
    }
    selected = []
    for proposal in proposals:
        if proposal.get("disposition") != "PENDING":
            continue
        parents = set(proposal.get("parents") or [])
        proposed = proposal.get("proposed_node")
        if isinstance(proposed, dict):
            parents.update(proposed.get("parents") or [])
        if (
            proposal.get("package_id") == package_id
            or _target_id(proposal) in chain
            or parents.intersection(chain)
        ):
            selected.append(proposal)
    return sorted(selected, key=lambda row: str(row.get("id", "")))


def _pending_decisions(
    decisions: list[dict[str, Any]],
    *,
    package_id: str,
    direction_id: str | None,
    experiment_ids: set[str],
) -> list[dict[str, Any]]:
    subjects = {value for value in {package_id, direction_id, *experiment_ids} if value}
    pending_values = {
        "PENDING",
        "AWAITING_ACK",
        "AWAITING_APPROVAL",
        "AWAITING_RATIFICATION",
        "ASK_USER",
    }
    selected = []
    for decision in decisions:
        pending = (
            decision.get("pending") is True
            or decision.get("requires_action") is True
            or decision.get("status") in pending_values
            or decision.get("outcome") in pending_values
            or decision.get("route") in pending_values
        )
        if not pending:
            continue
        if (
            decision.get("package_id") == package_id
            or decision.get("direction_id") == direction_id
            or decision.get("subject_id") in subjects
            or decision.get("experiment_id") in experiment_ids
        ):
            selected.append(decision)
    return sorted(selected, key=lambda row: str(row.get("id", "")))


def _scope_warnings(
    package: dict[str, Any],
    direction: dict[str, Any] | None,
    experiments: list[dict[str, Any]],
) -> list[str]:
    warnings_out = []
    direction_id = _direction_id(package)
    if not direction_id:
        warnings_out.append("package has no direction_id; Scope binding cannot be verified")
    elif direction is None:
        warnings_out.append(f"direction {direction_id} is missing from research state")
    elif direction.get("status", "ACTIVE") != "ACTIVE":
        warnings_out.append(
            f"direction {direction_id} is {direction.get('status')}"
        )
    if not experiments:
        warnings_out.append("package has no Experiment.spec in current state")
    return warnings_out


def _rule_applies(rule: dict[str, Any], package_id: str) -> bool:
    if rule.get("status") not in {"ACTIVE", "PROMOTED", "RULE_ACTIVE"}:
        return False
    level = rule.get("level")
    if level in {"universal", "project"}:
        return True
    if level != "package":
        return False
    scoped = rule.get("package_id") or rule.get("pkg")
    if scoped == package_id:
        return True
    scope = rule.get("scope") if isinstance(rule.get("scope"), dict) else {}
    return package_id in set(scope.get("packages") or [])


def _rule_text(rule: dict[str, Any]) -> str:
    return str(
        rule.get("text")
        or rule.get("content")
        or rule.get("description")
        or ""
    )


def _learning_applies(learning: dict[str, Any], package_id: str) -> bool:
    scoped = learning.get("package_id") or learning.get("pkg")
    if scoped in {None, "", "*", package_id}:
        return True
    scope = learning.get("scope") if isinstance(learning.get("scope"), dict) else {}
    packages = set(scope.get("packages") or [])
    return "*" in packages or package_id in packages


def _scope_version(
    state: dict[str, Any],
    direction_id: str | None,
    direction: dict[str, Any] | None,
) -> int:
    if direction_id:
        version = state["aggregate_versions"].get(f"direction/{direction_id}")
        if version is not None:
            return int(version)
    return int((direction or {}).get("version", 0) or 0)


def build(
    workspace: str | Path | ResearchPaths,
    pkg_id: str,
    *,
    research_root: str | Path | None = None,
    budget_chars: int = 8000,
    generated_at: str = "",
    state_snapshot: dict[str, Any] | None = None,
):
    """Return ``(package_pack, project_core_pack)`` without writing an artifact."""
    paths = _paths(workspace, research_root=research_root)
    state = state_snapshot if state_snapshot is not None else _management_state(paths)
    if not isinstance(state, dict) or not isinstance(state.get("aggregates"), dict):
        raise ValueError("state_snapshot must be a folded research-state object")
    packages = _packages_with_results(state)
    package = next((row for row in packages if row.get("id") == pkg_id), None)
    if package is None:
        raise KeyError(f"unknown package: {pkg_id}")

    direction_id = _direction_id(package)
    directions = _records(state, "direction")
    direction = next(
        (row for row in directions if row.get("id") == direction_id),
        None,
    )
    project = _project_for_direction(_records(state, "project"), direction)
    experiments = _package_experiments(
        _records(state, "experiment"),
        package,
        direction_id,
    )
    experiment_ids = {str(row.get("id")) for row in experiments if row.get("id")}
    provenance = _package_provenance(package, experiments)
    proposals = _pending_proposals(
        _records(state, "proposal"),
        package_id=pkg_id,
        project_id=str(project.get("id")) if project and project.get("id") else None,
        direction_id=direction_id,
        experiment_ids=experiment_ids,
    )
    pending_decisions = _pending_decisions(
        _records(state, "decision"),
        package_id=pkg_id,
        direction_id=direction_id,
        experiment_ids=experiment_ids,
    )

    rules = _records(state, "rule")
    package_rules = [
        _rule_text(rule)
        for rule in rules
        if _rule_applies(rule, pkg_id) and _rule_text(rule)
    ]
    project_rules = [
        _rule_text(rule)
        for rule in rules
        if rule.get("level") in {"universal", "project"}
        and rule.get("status") in {"ACTIVE", "PROMOTED", "RULE_ACTIVE"}
        and _rule_text(rule)
    ]
    learnings = [
        row
        for row in _records(state, "learning")
        if _learning_applies(row, pkg_id)
    ]
    papers = _records(state, "paper")
    edges = _records(state, "knowledge_edge")
    gaps = _records(state, "knowledge_gap")
    common = {
        "source_seq": state["source_seq"],
        "source_hash": state["source_hash"],
        "scope_version": _scope_version(state, direction_id, direction),
        "global_scope_version": state["source_seq"],
        "triage_version": sum(
            int(version)
            for key, version in state.get("aggregate_versions", {}).items()
            if str(key).startswith("proposal/")
        ),
        "generated_at": generated_at,
        "packages": packages,
        "analysis_rules": [],
        "papers_registry": papers,
        "edges": edges,
        "gaps": gaps,
    }
    full = assemble(
        {
            **common,
            "project_node": project,
            "direction_node": direction,
            "package": package,
            "experiment_nodes": experiments,
            "package_provenance": provenance,
            "pending_scope": proposals,
            "pending_decisions": pending_decisions,
            "scope_warnings": _scope_warnings(package, direction, experiments),
            "active_pkg": pkg_id,
            "learned_rules": package_rules,
            "learnings": learnings,
        },
        budget_chars=budget_chars,
    )
    core = assemble(
        {
            **common,
            "project_node": project,
            "direction_node": None,
            "package": None,
            "experiment_nodes": [],
            "package_provenance": {},
            "pending_scope": [],
            "pending_decisions": [],
            "scope_warnings": [],
            "active_pkg": None,
            "learned_rules": project_rules,
            "learnings": [
                row
                for row in _records(state, "learning")
                if not (row.get("package_id") or row.get("pkg"))
            ],
        },
        budget_chars=budget_chars,
    )
    return full, core


def query_json(
    workspace: str | Path | ResearchPaths,
    pkg_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return the package Context Pack as a JSON-ready ephemeral projection."""
    options = dict(kwargs)
    supplied_state = options.pop("state_snapshot", None)
    paths = _paths(workspace, research_root=options.pop("research_root", None))
    state = supplied_state if supplied_state is not None else _management_state(paths)
    full, _ = build(
        paths,
        pkg_id,
        state_snapshot=state,
        **options,
    )
    rendered = render_json(full)
    rendered["selection"] = _structured_selection(state, pkg_id)
    return rendered


def _structured_selection(
    state: dict[str, Any],
    package_id: str,
) -> dict[str, Any]:
    """Machine-readable controls and evidence retained beside prose sections."""
    package = state["aggregates"]["package"].get(package_id)
    if not isinstance(package, dict):
        raise KeyError(f"unknown package: {package_id}")
    direction_id = _direction_id(package)
    experiments = _package_experiments(
        _records(state, "experiment"),
        package,
        direction_id,
    )
    experiment_ids = {
        str(experiment["id"])
        for experiment in experiments
        if experiment.get("id")
    }
    pending_decisions = _pending_decisions(
        _records(state, "decision"),
        package_id=package_id,
        direction_id=direction_id,
        experiment_ids=experiment_ids,
    )
    rules = [
        rule
        for rule in _records(state, "rule")
        if _rule_applies(rule, package_id)
    ]
    learnings = [
        learning
        for learning in _records(state, "learning")
        if _learning_applies(learning, package_id)
    ]
    finalized_runs = [
        run
        for run in _records(state, "run")
        if run.get("package_id") == package_id
        and isinstance(run.get("latest_scientific_result"), dict)
    ]
    evidence_refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in [
        package,
        *experiments,
        *pending_decisions,
        *rules,
        *learnings,
        *(
            run["latest_scientific_result"]
            for run in finalized_runs
        ),
    ]:
        refs = (
            record.get("evidence_refs")
            or record.get("evidenceRefs")
            or record.get("evidence")
            or []
        )
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            identity = json.dumps(
                ref,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            if identity not in seen:
                seen.add(identity)
                evidence_refs.append(copy.deepcopy(ref))
    return {
        "package": {
            key: copy.deepcopy(package.get(key))
            for key in ("id", "lifecycle", "phase", "blocker")
        },
        "experiments": [
            {
                "id": experiment.get("id"),
                "status": experiment.get("status"),
                "control_mode": (
                    experiment.get("spec", {}).get("control_mode")
                    if isinstance(experiment.get("spec"), dict)
                    else None
                ),
            }
            for experiment in experiments
        ],
        "pending_decision_ids": [
            decision.get("id")
            for decision in pending_decisions
            if decision.get("id")
        ],
        "evidence_refs": evidence_refs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Query an ephemeral, state-backed Context Pack."
    )
    parser.add_argument("--pkg", required=True)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    parser.add_argument("--budget-chars", type=int, default=8000)
    parser.add_argument("--format", choices=("json", "md"), default="json")
    args = parser.parse_args(argv)
    if args.format == "md":
        full, _ = build(
            args.workspace,
            args.pkg,
            research_root=args.research_root,
            budget_chars=args.budget_chars,
        )
        print(render_md(full), end="")
    else:
        print(
            json.dumps(
                query_json(
                    args.workspace,
                    args.pkg,
                    research_root=args.research_root,
                    budget_chars=args.budget_chars,
                ),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
