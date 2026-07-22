from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from lib.interface import build_interface
from lib.interface.serve import make_handler, static_document_root
from lib.research_state import EventStore, ResearchPaths
from lib.research_state.schema import load_schema


ACTOR = {"type": "agent", "id": "interface-test"}


def _workspace(tmp_path: Path) -> tuple[ResearchPaths, EventStore]:
    paths = ResearchPaths.resolve(workspace=tmp_path)
    store = EventStore(paths)
    store.initialize()
    scope_store = EventStore(paths, migration_mode=True)
    scope_store.commit(
        event_type="AggregateUpserted",
        aggregate_type="project",
        aggregate_id="project/test",
        payload={
            "record": {
                "id": "project/test",
                "level": "project",
                "parents": [],
                "version": 1,
                "status": "ACTIVE",
                "source": "interface-test",
                "spec": {
                    "goal": "Validate the central-state interface projection.",
                    "contributions": ["One deterministic dashboard projection."],
                    "out_of_scope": ["No interface-owned research facts."],
                },
                "_scope_transition": {
                    "scope_version": 1,
                    "op": "create",
                    "gate": "USER_ONLY",
                },
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:project",
    )
    scope_store.commit(
        event_type="AggregateUpserted",
        aggregate_type="direction",
        aggregate_id="direction/test",
        payload={
            "record": {
                "id": "direction/test",
                "level": "direction",
                "parents": ["project/test"],
                "version": 2,
                "status": "ACTIVE",
                "source": "interface-test",
                "spec": {
                    "hypothesis": "The interface preserves formal Scope data.",
                    "metric": "projection fidelity",
                    "baselines": ["central research state"],
                    "success_gate": "all formal fields survive projection",
                },
                "_scope_transition": {
                    "scope_version": 2,
                    "op": "revise",
                    "gate": "USER_CROSS_MODEL_AUDIT",
                },
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:direction",
    )
    scope_store.commit(
        event_type="AggregateUpserted",
        aggregate_type="experiment",
        aggregate_id="scope-exp-one",
        payload={
            "record": {
                "id": "scope-exp-one",
                "local_id": "scope-exp-one",
                "package_id": None,
                "direction_id": "direction/test",
                "scope_status": "ACTIVE",
                "scope_version": 3,
                "scope_source": "interface-test",
                "scope_confirmation": "CONFIRMED",
                "confirmed_direction_version": 2,
                "status": "PLANNED",
                "spec": {
                    "purpose": "Validate formal Experiment projection.",
                    "config_ref": "configs/scope-test.yaml",
                    "gate": "formal fields match",
                    "control_mode": "CHECKPOINTED",
                },
                "_scope_transition": {
                    "scope_version": 3,
                    "op": "create",
                    "gate": "AGENT_DEFERRED_ACK",
                },
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:scope-experiment",
    )
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="package",
        aggregate_id="package-one",
        payload={
            "record": {
                "id": "package-one",
                "slug": "package-one",
                "name": "Package One",
                "lifecycle": "ACTIVE",
                "phase": "IMPLEMENTING",
                "blocker": None,
                "hypothesis": "The projection is deterministic.",
                "primaryMetric": "tree hash",
                "lastUpdated": "2026-07-20",
                "direction_id": "direction/test",
                "sourceDirection": "direction/test",
                "sourceVersion": 2,
                "sourceChange": "interface-test:direction",
                "sourceExperiments": [
                    {
                        "id": "scope-exp-one",
                        "version": 3,
                        "source": "interface-test",
                    }
                ],
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:package",
    )
    scope_store.commit(
        event_type="ExperimentBoundToPackage",
        aggregate_type="experiment",
        aggregate_id="scope-exp-one",
        payload={
            "patch": {
                "local_id": "exp-one",
                "package_id": "package-one",
                "status": "ACTIVE",
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:experiment",
        expected_version=1,
    )
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="brainstorm",
        aggregate_id="projection-idea",
        payload={
            "record": {
                "id": "projection-idea",
                "title": "Projection idea",
                "idea": "Rebuild every human page from central state.",
                "rough_metric": "tree hash",
                "created_at": "2026-07-20T00:00:00+00:00",
                "page_language": "en",
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:brainstorm",
    )
    return paths, store


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _browser_globals(script_path: Path) -> dict:
    program = """
const fs = require("fs");
const vm = require("vm");
const context = {window: {}};
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), context);
process.stdout.write(JSON.stringify(context.window));
"""
    result = subprocess.run(
        ["node", "-e", program, str(script_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_rebuild_is_deterministic_and_does_not_trust_destination(tmp_path: Path) -> None:
    paths, _ = _workspace(tmp_path)
    first = build_interface(paths)
    expected = _tree_hash(first.root)

    (paths.interface / "data" / "research-packages.js").write_text(
        "window.RESEARCH_PACKAGES = ['manual authority'];\n", encoding="utf-8"
    )
    (paths.interface / "manual-only.txt").write_text("must disappear", encoding="utf-8")

    second = build_interface(paths)
    assert _tree_hash(second.root) == expected
    assert not (second.root / "manual-only.txt").exists()


def test_package_tracker_rows_are_derived_from_run_and_resource_state(
    tmp_path: Path,
) -> None:
    paths, store = _workspace(tmp_path)
    store.commit(
        event_type="RunLaunchAuthorized",
        aggregate_type="run",
        aggregate_id="run-one",
        payload={
            "record": {
                "id": "run-one",
                "run_id": "run-one",
                "package_id": "package-one",
                "experiment_id": "scope-exp-one",
                "experiment_local_id": "exp-one",
                "status": "QUEUED",
                "dir": "experiments/package-one/exp-one/run-one",
                "resource": {"alloc_id": "alloc-one"},
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:run",
    )
    store.commit(
        event_type="ResourceAllocationCreated",
        aggregate_type="resource_allocation",
        aggregate_id="alloc-one",
        payload={
            "record": {
                "id": "alloc-one",
                "alloc_id": "alloc-one",
                "server": "local",
                "package_id": "package-one",
                "experiment_id": "scope-exp-one",
                "gpu_count": 1,
                "gpu_type": "RTX-4090",
                "gpu_ids": ["0"],
                "reason": "projection test",
                "status": "OPEN",
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:allocation",
    )

    build_interface(paths)
    projected = _browser_globals(
        paths.interface / "data" / "research-packages.js"
    )["RESEARCH_PACKAGES"][0]
    assert projected["liveChecks"][0]["run_id"] == "run-one"
    assert projected["liveChecks"][0]["run_state"] == "QUEUED"
    assert projected["resourceAllocations"][0]["assigned"] == "0"
    assert projected["resourceAllocations"][0]["capacity"] == "1 x RTX-4090"
    assert projected["openRuns"] == "run-one"


def test_concurrent_rebuilds_cannot_publish_a_stale_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_root))
    paths, store = _workspace(tmp_path)
    build_module = importlib.import_module("lib.interface.build")
    original_lock = build_module._interface_projection_lock
    original_copy = build_module._copy_static_bundle
    old_snapshot_read = threading.Event()
    release_old_renderer = threading.Event()
    new_lock_attempted = threading.Event()
    new_lock_acquired = threading.Event()
    results = {}
    errors: list[BaseException] = []

    @contextmanager
    def observed_lock(selected_paths: ResearchPaths):
        if threading.current_thread().name == "interface-new":
            new_lock_attempted.set()
        with original_lock(selected_paths):
            if threading.current_thread().name == "interface-new":
                new_lock_acquired.set()
            yield

    def delayed_copy(stage: Path, bundle: Path):
        if threading.current_thread().name == "interface-old":
            old_snapshot_read.set()
            if not release_old_renderer.wait(timeout=5):
                raise TimeoutError("test did not release the stale renderer")
        return original_copy(stage, bundle)

    monkeypatch.setattr(build_module, "_interface_projection_lock", observed_lock)
    monkeypatch.setattr(build_module, "_copy_static_bundle", delayed_copy)

    def render(label: str) -> None:
        try:
            results[label] = build_interface(paths)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    old_thread = threading.Thread(
        target=render,
        args=("old",),
        name="interface-old",
    )
    new_thread = threading.Thread(
        target=render,
        args=("new",),
        name="interface-new",
    )
    old_thread.start()
    assert old_snapshot_read.wait(timeout=5)

    updated_hypothesis = "The latest serialized projection wins."
    store.commit(
        event_type="AggregatePatched",
        aggregate_type="package",
        aggregate_id="package-one",
        payload={"patch": {"hypothesis": updated_hypothesis}},
        actor=ACTOR,
        idempotency_key="interface-test:concurrent-new-state",
    )
    latest_state = store.state()

    try:
        new_thread.start()
        assert new_lock_attempted.wait(timeout=5)
        assert not new_lock_acquired.is_set()
    finally:
        release_old_renderer.set()
        old_thread.join(timeout=10)
        new_thread.join(timeout=10)

    assert not old_thread.is_alive()
    assert not new_thread.is_alive()
    assert errors == []
    assert results["old"].source_seq < results["new"].source_seq
    assert results["new"].source_seq == latest_state["source_seq"]
    assert results["new"].source_hash == latest_state["source_hash"]
    assert (paths.runtime / "interface-projection.lock").is_file()
    assert paths.runtime.is_relative_to(runtime_root)
    assert not (paths.root / "interface-projection.lock").exists()
    projected = _browser_globals(
        paths.interface / "data" / "research-packages.js"
    )
    assert projected["RESEARCH_PACKAGES"][0]["hypothesis"] == updated_hypothesis


def test_self_evolution_data_is_written_only_by_interface_rebuild(
    tmp_path: Path,
) -> None:
    paths, _ = _workspace(tmp_path)
    result = build_interface(paths)

    projected = json.loads(
        (result.root / "data" / "self-evolution.json").read_text(encoding="utf-8")
    )
    browser = _browser_globals(result.root / "data" / "self-evolution.js")
    assert browser["RESEARCH_SELF_EVOLUTION"] == projected
    assert projected["counts"] == {
        "active_rules": 0,
        "active_skills": 0,
        "rules": 0,
        "skills": 0,
    }


def test_failed_build_leaves_previous_snapshot_untouched(tmp_path: Path) -> None:
    paths, store = _workspace(tmp_path)
    first = build_interface(paths)
    expected = _tree_hash(first.root)
    missing_hash = "0" * 64
    store.commit(
        event_type="AggregatePatched",
        aggregate_type="package",
        aggregate_id="package-one",
        payload={
            "patch": {
                "interface_notes": {
                    "analysis.html": {
                        "uri": f"state/notes/{missing_hash}.blob",
                        "sha256": missing_hash,
                        "mime": "text/html",
                        "title": "missing",
                    }
                }
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:missing-note",
    )

    with pytest.raises(FileNotFoundError):
        build_interface(paths)
    assert _tree_hash(paths.interface) == expected
    assert not list(paths.root.glob(".interface-build-*"))
    assert not list(paths.root.glob(".interface-backup-*"))


def test_brainstorm_detail_note_overrides_template_with_path_only_rewrite(
    tmp_path: Path,
) -> None:
    paths, store = _workspace(tmp_path)
    note = store.write_note(
        (
            "<!doctype html><html><body data-page=\"brainstorm\">"
            "<p>custom human detail</p>"
            "<code>research_html/brainstorm/projection-idea.html</code>"
            "<code>outputs/package-one/runs/run-one/log.txt</code>"
            "</body></html>"
        ),
        mime="text/html",
        title="legacy brainstorm detail",
    )
    store.commit(
        event_type="AggregatePatched",
        aggregate_type="brainstorm",
        aggregate_id="projection-idea",
        payload={"patch": {"detail_note": note}},
        actor=ACTOR,
        idempotency_key="interface-test:brainstorm-note",
    )

    result = build_interface(paths)
    page = (
        result.root / "brainstorm" / "2026-07-20-projection-idea.html"
    ).read_text(encoding="utf-8")
    assert "custom human detail" in page
    assert ".research/interface/brainstorm/projection-idea.html" in page
    assert ".research/experiments/package-one/runs/run-one/log.txt" in page
    assert "research_html" not in page
    assert "outputs/" not in page


def test_brainstorm_document_note_is_wrapped_by_shared_document_shell(
    tmp_path: Path,
) -> None:
    paths, store = _workspace(tmp_path)
    body = (
        '<section class="doc-section wide" id="audit">'
        '<h2><span class="section-number">01 </span><span>Causal audit</span></h2>'
        '<div class="table-wrap"><table class="doc-table">'
        '<caption>Claim boundary</caption><thead><tr>'
        '<th scope="col">Observable</th><th scope="col">Not observable</th>'
        '</tr></thead><tbody><tr><td>Query</td><td>Hidden goal</td></tr></tbody>'
        '</table></div><figure class="research-figure">'
        '<figcaption>Figure 1. Shared question and dependent stages.</figcaption>'
        '</figure></section>'
    )
    note = store.write_note(
        body,
        mime="text/html;profile=brainstorm-fragment",
        title="projection brainstorm body",
    )
    store.commit(
        event_type="AggregatePatched",
        aggregate_type="brainstorm",
        aggregate_id="projection-idea",
        payload={
            "patch": {
                "abstract": "One full draft, revised in place.",
                "idea_snapshot": {
                    "Core question": "Can the claim be observed?",
                    "Authority": "Pre-package only",
                },
                "document_note": note,
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:brainstorm-document-note",
    )

    result = build_interface(paths)
    page = (
        result.root / "brainstorm" / "2026-07-20-projection-idea.html"
    ).read_text(encoding="utf-8")
    assert 'data-page="brainstorm-document"' in page
    assert '<link rel="stylesheet" href="../assets/brainstorm.css">' in page
    assert "Abstract / TLDR" in page
    assert "Idea Snapshot" in page
    assert "data-docs-toc" in page
    assert "One full draft, revised in place." in page
    assert "Can the claim be observed?" in page
    assert "Claim boundary" in page
    assert "Figure 1. Shared question and dependent stages." in page
    assert "Revision 2" in page
    assert "<style>" not in page
    assert (result.root / "assets" / "brainstorm.css").read_bytes() == (
        REPO
        / "skills"
        / "research-dashboard"
        / "assets"
        / "dashboard"
        / "assets"
        / "brainstorm.css"
    ).read_bytes()


def test_invalid_brainstorm_document_note_preserves_previous_interface(
    tmp_path: Path,
) -> None:
    paths, store = _workspace(tmp_path)
    build_interface(paths)
    expected = _tree_hash(paths.interface)
    note = store.write_note(
        "<!doctype html><html><body><h2>Full page</h2></body></html>",
        mime="text/html;profile=brainstorm-fragment",
        title="invalid full page",
    )
    store.commit(
        event_type="AggregatePatched",
        aggregate_type="brainstorm",
        aggregate_id="projection-idea",
        payload={"patch": {"document_note": note}},
        actor=ACTOR,
        idempotency_key="interface-test:invalid-brainstorm-document-note",
    )

    with pytest.raises(ValueError, match="page-shell"):
        build_interface(paths)
    assert _tree_hash(paths.interface) == expected
    assert not list(paths.root.glob(".interface-build-*"))
    assert not list(paths.root.glob(".interface-backup-*"))


def test_package_interface_note_restores_human_html(tmp_path: Path) -> None:
    paths, store = _workspace(tmp_path)
    note = store.write_note(
        (
            "<!doctype html><html><body data-page=\"plan\" "
            "data-package-id=\"package-one\">"
            "<article data-card=\"human-plan\">Keep this layout</article>"
            "<code>research_html/packages/package-one/plan.html</code>"
            "</body></html>"
        ),
        mime="text/html",
        title="package-one/plan.html",
    )
    store.commit(
        event_type="AggregatePatched",
        aggregate_type="package",
        aggregate_id="package-one",
        payload={"patch": {"interface_notes": {"plan.html": note}}},
        actor=ACTOR,
        idempotency_key="interface-test:package-note",
    )

    result = build_interface(paths)
    plan = (
        result.root / "packages" / "package-one" / "plan.html"
    ).read_text(encoding="utf-8")
    assert 'data-card="human-plan"' in plan
    assert "Keep this layout" in plan
    assert ".research/interface/packages/package-one/plan.html" in plan
    assert "research_html" not in plan


def test_projection_has_no_python_script_surface(tmp_path: Path) -> None:
    paths, _ = _workspace(tmp_path)
    result = build_interface(paths)

    assert not (result.root / "scripts").exists()
    assert not [path for path in result.root.rglob("*.py")]
    assert (result.root / "module.html").is_file()
    assert (result.root / "packages" / "package-one" / "plan.html").is_file()
    assert (
        result.root / "brainstorm" / "2026-07-20-projection-idea.html"
    ).is_file()
    assert 'id="package-module-root"' in (result.root / "module.html").read_text()
    inventory = _browser_globals(result.root / "data" / "research-packages.js")
    experiment = inventory["RESEARCH_PACKAGES"][0]["experiments"][0]
    assert experiment["id"] == "scope-exp-one"
    assert experiment["localId"] == "exp-one"
    research_js = (result.root / "assets" / "research.js").read_text()
    assert "function experimentDisplayId(exp)" in research_js
    assert "var id = experimentDisplayId(e);" in research_js
    assert (
        (result.root / "assets" / "research.css").read_bytes()
        == (
            REPO
            / "skills"
            / "research-dashboard"
            / "assets"
            / "dashboard"
            / "assets"
            / "research.css"
        ).read_bytes()
    )
    scope_html = (result.root / "scope.html").read_text(encoding="utf-8")
    assert "<code>data/scope-transitions.jsonl</code> in the browser" in scope_html
    assert (
        ".research/state/events.jsonl (projected scope transitions)</code> directly"
        not in scope_html
    )


def test_dashboard_checked_brainstorm_lane_renders_brainstorm_cards(
    tmp_path: Path,
) -> None:
    paths, _ = _workspace(tmp_path)
    build_interface(paths)
    executable = shutil.which("chromium") or shutil.which("chromium-browser")
    if not executable:
        pytest.skip("dashboard browser test requires Chromium")

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(paths, started_at=0.0)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        rendered = subprocess.run(
            [
                executable,
                "--headless=new",
                "--no-sandbox",
                "--disable-background-networking",
                "--virtual-time-budget=2000",
                "--dump-dom",
                f"http://127.0.0.1:{port}/index.html",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert 'name="lane" value="brainstorm" checked' in rendered
    assert 'data-brainstorm-id="projection-idea"' in rendered
    assert 'data-card-kind="brainstorm"' in rendered
    assert 'data-card-kind="package"' in rendered
    assert "Projection idea" in rendered
    assert rendered.count('<header class="card-top">') == 2
    assert rendered.count('<div class="card-body">') == 2
    assert rendered.count('<footer class="card-footer">') == 2
    assert 'class="bi-top"' not in rendered
    assert 'class="bi-body"' not in rendered


def test_scope_projection_preserves_formal_experiment_contract(
    tmp_path: Path,
) -> None:
    paths, _ = _workspace(tmp_path)
    result = build_interface(paths)
    projection = json.loads(
        (result.root / "data" / "scope-projection.json").read_text(
            encoding="utf-8"
        )
    )
    experiment = projection["scope-exp-one"]

    assert experiment == {
        "id": "scope-exp-one",
        "level": "experiment",
        "parents": ["direction/test"],
        "source": "interface-test",
        "spec": {
            "purpose": "Validate formal Experiment projection.",
            "config_ref": "configs/scope-test.yaml",
            "gate": "formal fields match",
            "control_mode": "CHECKPOINTED",
        },
        "status": "ACTIVE",
        "version": 3,
    }
    assert "_scope_transition" not in projection["project/test"]
    assert "_scope_transition" not in projection["direction/test"]

    transitions = [
        json.loads(line)
        for line in (
            result.root / "data" / "scope-transitions.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line
    ]
    by_node = {row["node_id"]: row for row in transitions}
    assert by_node["direction/test"]["op"] == "revise"
    assert by_node["scope-exp-one"]["gate"] == "AGENT_DEFERRED_ACK"


def test_package_projection_uses_formal_scope_experiment_provenance(
    tmp_path: Path,
) -> None:
    paths, _ = _workspace(tmp_path)
    result = build_interface(paths)
    browser = _browser_globals(result.root / "data" / "research-packages.js")
    package = browser["RESEARCH_PACKAGES"][0]

    assert package["sourceExperiments"] == [
        {
            "id": "scope-exp-one",
            "version": 3,
            "source": "interface-test",
        }
    ]
    assert package["experiments"][0]["id"] == "scope-exp-one"
    assert "aliases" not in package["experiments"][0]


def test_package_projection_derives_a_concise_card_summary(tmp_path: Path) -> None:
    paths, store = _workspace(tmp_path)
    store.commit(
        event_type="AggregatePatched",
        aggregate_type="package",
        aggregate_id="package-one",
        payload={
            "patch": {
                "title": "A clear research package title",
                "problem": "A deliberately long Direction statement.",
                "motivation": "The Scope is ratified.",
                "idea_snapshot": [
                    {"label": "Core question", "value": "Can feedback help?"}
                ],
                "objectiveContract": {
                    "hypothesisOneLine": "Feedback improves retrieval.",
                    "successPredicate": "Complete an auditable evaluation.",
                    "metric": "Record R@1, repair, harm, cost, and latency.",
                },
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:card-summary",
    )

    result = build_interface(paths)
    package = _browser_globals(
        result.root / "data" / "research-packages.js"
    )["RESEARCH_PACKAGES"][0]

    assert package["cardSummary"] == {
        "title": "A clear research package title",
        "question": "Can feedback help?",
        "hypothesis": "Feedback improves retrieval.",
        "motivation": "The Scope is ratified.",
        "completionGate": "Complete an auditable evaluation.",
        "measurements": "Record R@1, repair, harm, cost, and latency.",
    }


def test_package_hero_lead_uses_the_package_abstract(tmp_path: Path) -> None:
    paths, store = _workspace(tmp_path)
    store.commit(
        event_type="AggregatePatched",
        aggregate_type="package",
        aggregate_id="package-one",
        payload={
            "patch": {
                "abstract": "First reproduce the method, then test its transfer.",
                "problem": "Can the method transfer to another task?",
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:package-abstract",
    )

    result = build_interface(paths)
    overview = (
        result.root / "packages" / "package-one" / "index.html"
    ).read_text(encoding="utf-8")

    assert (
        '<p class="lead">First reproduce the method, then test its transfer.</p>'
        in overview
    )
    assert (
        '<span class="identity-tldr-v">Can the method transfer to another task?</span>'
        in overview
    )


def test_browser_schema_is_generated_from_central_schema(tmp_path: Path) -> None:
    paths, _ = _workspace(tmp_path)
    result = build_interface(paths)
    browser = _browser_globals(result.root / "data" / "schema.js")
    central = load_schema()

    assert browser["RESEARCH_STATE_ENUMS"] == central["enums"]
    assert browser["RESEARCH_STATE_COMPATIBILITY"] == central["compatibility"]
    assert browser["NEXT_ROUTE"] == central["enums"]["decision_route"]
    assert browser["EXPERIMENT_VERDICT"] == central["enums"]["result_verdict"]
    assert browser["RESULT_VALIDITY"] == central["enums"]["result_validity"]


def test_server_document_root_is_only_interface(tmp_path: Path) -> None:
    paths, _ = _workspace(tmp_path)
    build_interface(paths)
    (tmp_path / "workspace-secret.txt").write_text("not public", encoding="utf-8")

    assert static_document_root(paths) == paths.interface.resolve()
    assert static_document_root(paths) != paths.workspace.resolve()
    assert static_document_root(paths) != paths.root.resolve()
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(paths, started_at=0.0)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(base + "/index.html", timeout=2) as response:
            assert response.status == 200
        try:
            urllib.request.urlopen(base + "/workspace-secret.txt", timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("workspace file escaped the interface document root")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_live_api_reads_state_and_experiment_runtime_not_interface(
    tmp_path: Path,
) -> None:
    paths, store = _workspace(tmp_path)
    run_dir = paths.run_dir("package-one", "exp-one", "run-one")
    run_dir.mkdir(parents=True)
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "run_id": "run-one",
                "pkg": "package-one",
                "exp_id": "package-one::exp-one",
                "status": "RUNNING",
                "progress": {"pct": 25},
            }
        ),
        encoding="utf-8",
    )
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="run",
        aggregate_id="run-one",
        payload={
            "record": {
                "id": "run-one",
                "package_id": "package-one",
                "experiment_id": "package-one::exp-one",
                "status": "RUNNING",
                "dir": run_dir.relative_to(paths.root).as_posix(),
            }
        },
        actor=ACTOR,
        idempotency_key="interface-test:run",
    )
    build_interface(paths)
    (paths.interface / "data" / "live-runs.jsonl").write_text(
        '{"run_id":"forged-interface-run"}\n', encoding="utf-8"
    )

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(paths, started_at=0.0)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = (
            f"http://127.0.0.1:{server.server_port}"
            "/api/live/runs?include_status=1"
        )
        with urllib.request.urlopen(url, timeout=2) as response:
            payload = json.loads(response.read())
        assert [row["run_id"] for row in payload["runs"]] == ["run-one"]
        assert payload["runs"][0]["status"]["progress"]["pct"] == 25
        assert payload["runs"][0]["exp_id"] == "package-one::exp-one"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_dashboard_entrypoint_refuses_implicit_legacy_upgrade(tmp_path: Path) -> None:
    (tmp_path / "research_html").mkdir()
    script = (
        REPO
        / "skills"
        / "research-dashboard"
        / "scripts"
        / "ensure_dashboard.py"
    )
    result = subprocess.run(
        [sys.executable, str(script), "--workspace", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "upgrade-required" in result.stderr
    assert not (tmp_path / ".research" / "VERSION").exists()


def test_dashboard_entrypoint_refuses_implicit_greenfield_init(tmp_path: Path) -> None:
    script = (
        REPO
        / "skills"
        / "research-dashboard"
        / "scripts"
        / "ensure_dashboard.py"
    )
    result = subprocess.run(
        [sys.executable, str(script), "--workspace", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "research-init" in result.stderr
    assert not (tmp_path / ".research").exists()
