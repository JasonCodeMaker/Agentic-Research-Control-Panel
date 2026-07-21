from __future__ import annotations

import importlib.util
from pathlib import Path

from lib.research_state import EventStore, ResearchPaths


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = ROOT / "skills" / "research-analysis" / "scripts"
ACTOR = {"type": "agent", "id": "research-analysis-test"}


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


init_analysis_page = _module("init_analysis_page")
lint_analysis = _module("lint_analysis")


def _package(tmp_path: Path) -> ResearchPaths:
    paths = ResearchPaths.resolve(workspace=tmp_path)
    store = EventStore(paths)
    store.initialize()
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="package",
        aggregate_id="pkg",
        payload={
            "record": {
                "id": "pkg",
                "lifecycle": "ACTIVE",
                "phase": "IMPLEMENTING",
                "blocker": None,
                "direction_id": "direction/pkg",
                "sourceVersion": 1,
                "sourceChange": "test",
                "sourceExperiments": [],
                "pages": ["index"],
            }
        },
        actor=ACTOR,
        idempotency_key="research-analysis:test-package",
    )
    return paths


def test_init_updates_state_and_rebuilds_interface(tmp_path: Path) -> None:
    paths = _package(tmp_path)

    result = init_analysis_page.enable_analysis(paths, "pkg")

    package = EventStore(paths).state()["aggregates"]["package"]["pkg"]
    assert result["changed"] is True
    assert result["interface_written"] is True
    assert "analysis" in package["pages"]
    assert (paths.interface / "packages/pkg/analysis.html").is_file()


def test_init_is_idempotent(tmp_path: Path) -> None:
    paths = _package(tmp_path)
    init_analysis_page.enable_analysis(paths, "pkg")

    result = init_analysis_page.enable_analysis(paths, "pkg")

    assert result["changed"] is False
    assert result["event_id"] is None


def test_read_operations_do_not_initialize_a_workspace(
    tmp_path: Path,
    capsys,
) -> None:
    paths = ResearchPaths.resolve(workspace=tmp_path)

    rc = lint_analysis.main(["--workspace", str(tmp_path), "--all"])

    assert rc == 2
    assert "not initialized" in capsys.readouterr().err
    assert not paths.root.exists()


def test_lint_reads_analysis_contract_from_state(tmp_path: Path) -> None:
    paths = _package(tmp_path)
    init_analysis_page.enable_analysis(paths, "pkg")

    assert (
        lint_analysis.main(
            ["--workspace", str(tmp_path), "--package-id", "pkg"]
        )
        == 0
    )
