from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from lib.research_state import EventStore, ResearchPaths, StateQuery, UpgradeRequired


ROOT = Path(__file__).resolve().parents[2]
AGENT_READERS = (
    ROOT / "skills/research-analysis/scripts/init_analysis_page.py",
    ROOT / "skills/research-analysis/scripts/lint_analysis.py",
    ROOT / "skills/research-brainstorm/scripts/brainstorm.py",
    ROOT / "skills/research-auto/scripts/conductor.py",
    ROOT / "skills/research-package/scripts/draft_package.py",
    ROOT / "skills/research-package/scripts/create_from_scope.py",
)
ACTOR = {"type": "system", "id": "agent-read-boundary-test"}


def _load(name: str, relative: str) -> ModuleType:
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upsert(
    store: EventStore,
    aggregate_type: str,
    aggregate_id: str,
    record: dict,
) -> None:
    store.commit(
        event_type="AggregateImported",
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload={"record": record},
        actor=ACTOR,
        idempotency_key=f"agent-read-boundary:{aggregate_type}:{aggregate_id}",
        expected_version=0,
    )


def test_agent_readers_use_queries_and_never_open_interface_state() -> None:
    violations: list[str] = []
    for path in AGENT_READERS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {alias.name for alias in node.names}
                if "EventStore" in names:
                    violations.append(f"{path.name}: imports EventStore")
            if isinstance(node, ast.Attribute) and node.attr == "interface":
                violations.append(f"{path.name}: accesses a paths.interface surface")
            if not isinstance(node, ast.Call) or not isinstance(
                node.func,
                ast.Attribute,
            ):
                continue
            if node.func.attr in {"state", "events"}:
                violations.append(f"{path.name}: calls {node.func.attr}()")
            if node.func.attr == "initialize":
                allowed = (
                    path.name == "brainstorm.py"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "management"
                )
                if not allowed:
                    violations.append(f"{path.name}: initializes on a read path")
    assert violations == []


def test_unversioned_agent_reads_fail_closed_without_creating_state(
    tmp_path: Path,
) -> None:
    analysis = _load(
        "agent_boundary_analysis",
        "skills/research-analysis/scripts/init_analysis_page.py",
    )
    brainstorm = _load(
        "agent_boundary_brainstorm",
        "skills/research-brainstorm/scripts/brainstorm.py",
    )
    conductor = _load(
        "agent_boundary_conductor",
        "skills/research-auto/scripts/conductor.py",
    )
    package = _load(
        "agent_boundary_package",
        "skills/research-package/scripts/create_from_scope.py",
    )
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})

    with pytest.raises(FileNotFoundError):
        analysis.enable_analysis(paths, "missing")
    with pytest.raises(UpgradeRequired):
        brainstorm.read_brainstorms(paths)
    with pytest.raises(UpgradeRequired):
        brainstorm.active_project_context(paths)
    with pytest.raises(UpgradeRequired):
        conductor.campaign_cycles(paths, "direction/missing")
    with pytest.raises(UpgradeRequired):
        package.materialization_status(
            paths=paths,
            direction_id="direction/missing",
            package_id="missing",
        )

    assert not paths.version_file.exists()
    assert not paths.current.exists()
    assert not paths.root.exists()


def test_typed_agent_slices_are_stamped_and_exclude_unrelated_state(
    tmp_path: Path,
) -> None:
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    EventStore(paths).initialize()
    store = EventStore(paths, migration_mode=True)
    _upsert(
        store,
        "project",
        "project/p",
        {
            "id": "project/p",
            "status": "ACTIVE",
            "spec": {"goal": "Bound reads", "out_of_scope": ["full state"]},
            "unrelated": "must-not-leak",
        },
    )
    _upsert(
        store,
        "brainstorm",
        "idea",
        {"id": "idea", "title": "Typed slices", "status": "ACTIVE"},
    )
    _upsert(
        store,
        "direction",
        "direction/d",
        {
            "id": "direction/d",
            "level": "direction",
            "status": "ACTIVE",
            "version": 1,
            "spec": {"success_gate": "score >= 1"},
            "unrelated": "must-not-leak",
        },
    )
    _upsert(
        store,
        "package",
        "pkg",
        {
            "id": "pkg",
            "direction_id": "direction/d",
            "lifecycle": "ACTIVE",
            "pages": ["analysis"],
            "analysisInsights": [{"id": "insight"}],
            "unrelated": "must-not-leak",
        },
    )
    _upsert(
        store,
        "rule",
        "pkg#rule",
        {
            "id": "pkg#rule",
            "package_id": "pkg",
            "kind": "lesson",
            "status": "ACTIVE",
            "text": "Use bounded reads.",
            "rationale": "insight",
            "unrelated": "must-not-leak",
        },
    )
    _upsert(
        store,
        "experiment",
        "experiment/d/unbound",
        {
            "id": "experiment/d/unbound",
            "direction_id": "direction/d",
            "package_id": None,
            "scope_status": "ACTIVE",
            "scope_version": 1,
            "scope_source": "test",
            "spec": {"purpose": "materialize"},
            "unrelated": "must-not-leak",
        },
    )
    _upsert(
        store,
        "experiment",
        "experiment/d/bound",
        {
            "id": "experiment/d/bound",
            "local_id": "P0",
            "direction_id": "direction/d",
            "package_id": "pkg",
            "status": "READY",
            "unrelated": "must-not-leak",
        },
    )
    _upsert(
        store,
        "learning",
        "unrelated-learning",
        {"id": "unrelated-learning", "secret": "must-not-leak"},
    )

    query = StateQuery(paths)
    results = (
        query.analysis("pkg"),
        query.brainstorms(include_archived=True),
        query.project_boundary(),
        query.campaign("direction/d"),
        query.materialization("direction/d", "new-pkg"),
    )
    state = EventStore(paths).state()
    for result in results:
        assert set(result) == {"source_seq", "source_hash", "data"}
        assert result["source_seq"] == state["source_seq"]
        assert result["source_hash"] == state["source_hash"]
        assert "unrelated-learning" not in json.dumps(result, sort_keys=True)
        assert "must-not-leak" not in json.dumps(result, sort_keys=True)

    analysis = results[0]["data"]
    assert set(analysis) == {"packages", "rules"}
    assert set(analysis["packages"][0]) == {
        "id",
        "pages",
        "analysisInsights",
    }
    campaign = results[3]["data"]
    assert set(campaign) == {
        "direction",
        "pending_directions",
        "packages",
        "experiments",
        "campaign",
        "campaign_version",
        "run",
    }
    materialization = results[4]["data"]
    assert set(materialization) == {
        "direction",
        "experiments",
        "pending",
        "package_exists",
        "package_version",
        "latest_direction_event_id",
        "source_brainstorms",
        "source_brainstorm_ids",
        "missing_source_brainstorms",
        "source_proposal_id",
        "source_package",
        "draft_package",
        "draft_binding_valid",
        "package_lifecycle",
    }
