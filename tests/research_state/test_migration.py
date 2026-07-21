import hashlib
import json
from pathlib import Path

import pytest

from lib.experiments.contracts import (
    verify_result_evidence,
    verify_run_files,
)
from lib.experiments.reconcile import reconcile_runs
from lib.research_state import migration
from lib.research_state.migration import MigrationError, check, inventory, migrate
from lib.research_state.paths import (
    ResearchPaths,
    UnsupportedResearchVersion,
)
from lib.research_state.store import EventStore


def _jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _legacy_workspace(root: Path):
    data = root / "research_html" / "data"
    data.mkdir(parents=True)
    (data / "research-packages.js").write_text(
        """
window.RESEARCH_PACKAGES = [{
  id: "pkg-1",
  name: "Package",
  category: "in-progress",
  status: "BLOCKED",
  currentBlocker: "waiting",
  experiments: [{
    id: "exp-1",
    status: "queued",
    sourceTask: "task-1",
    after: ["invented"]
  }]
}];
""",
        encoding="utf-8",
    )
    (data / "brainstorms.js").write_text(
        'window.BRAINSTORMS = [{id: "idea-1", title: "Idea"}];\n',
        encoding="utf-8",
    )
    (data / "rules.js").write_text(
        'window.RESEARCH_RULES = [{id: "R1", kind: "form", level: "universal"}];\n',
        encoding="utf-8",
    )
    _jsonl(data / "papers.jsonl", [{"id": "paper-1", "title": "Paper"}])
    _jsonl(data / "edges.jsonl", [{"from": "paper-1", "to": "gap-1", "type": "ADDRESSES_GAP"}])
    _jsonl(data / "gaps.jsonl", [{"id": "gap-1", "summary": "Gap"}])

    _jsonl(
        root / "outputs" / "_scope" / "transitions.jsonl",
        [
            {
                "transaction_id": "txn-project-1",
                "scope_version": 1,
                "op": "create",
                "gate": "USER_ONLY",
                "node": {
                    "id": "project-1",
                    "level": "project",
                    "parents": [],
                    "version": 1,
                    "status": "ACTIVE",
                    "spec": {"objective": "Preserve the migration fixture."},
                    "source": "test",
                },
            },
            {
                "transaction_id": "txn-direction-1",
                "scope_version": 1,
                "op": "create",
                "gate": "USER_CROSS_MODEL_AUDIT",
                "node": {
                    "id": "direction-1",
                    "level": "direction",
                    "parents": ["project-1"],
                    "version": 1,
                    "status": "ACTIVE",
                    "spec": {"hypothesis": "The migration remains lossless."},
                    "source": "test",
                },
            },
            {
                "transaction_id": "txn-1",
                "scope_version": 1,
                "op": "create",
                "gate": "AGENT_DEFERRED_ACK",
                "node": {
                    "id": "task-1",
                    "level": "task",
                    "parents": ["direction-1"],
                    "version": 1,
                    "status": "ACTIVE",
                    "spec": {
                        "experiment": "purpose",
                        "config": "config.yaml",
                        "gate": "metric >= 1",
                        "control_mode": "CHECKPOINTED",
                    },
                    "source": "test",
                },
            }
        ],
    )
    _jsonl(
        root / "outputs" / "_scope" / "triage.jsonl",
        [{"id": "proposal-1", "status": "pending", "proposed_node": {"id": "direction-1"}}],
    )
    prior = root / "outputs" / "_scope" / "prior_knowledge.md"
    prior.write_text("# Prior\n", encoding="utf-8")
    page = root / "research_html" / "packages" / "pkg-1" / "plan.html"
    page.parent.mkdir(parents=True)
    page.write_text("<html><body>Plan</body></html>\n", encoding="utf-8")
    brainstorm_page = root / "research_html" / "brainstorm" / "2026-06-03-idea-1.html"
    brainstorm_page.parent.mkdir(parents=True)
    brainstorm_page.write_text(
        "<html><body><section id=\"human-note\">Keep me</section></body></html>\n",
        encoding="utf-8",
    )


def _legacy_run(
    root: Path,
    *,
    status: str,
    experiment_id: str | None = "exp-1",
    run_id: str = "run-1",
) -> Path:
    run_dir = root / "outputs" / "pkg-1" / "runs" / run_id
    run_dir.mkdir(parents=True)
    meta = {
        "run_id": run_id,
        "pkg": "pkg-1",
        "command": ["python", "train.py"],
        "cwd": str(root),
        "started_at": 10.0,
        "custom_legacy_field": {"must": "survive"},
    }
    if experiment_id is not None:
        meta["exp_id"] = experiment_id
    (run_dir / "meta.json").write_text(
        json.dumps(meta),
        encoding="utf-8",
    )
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "pkg": "pkg-1",
                **({"exp_id": experiment_id} if experiment_id is not None else {}),
                "status": status,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "log.txt").write_text("measured\n", encoding="utf-8")
    rows = [
        {
            "op": "launched",
            "run_id": run_id,
            "pkg": "pkg-1",
            **({"exp_id": experiment_id} if experiment_id is not None else {}),
            "dir": str(run_dir),
            "started_at": 10.0,
        }
    ]
    if status in {"COMPLETED", "FAILED", "HALTED", "SKIPPED"}:
        rows.append(
            {
                "op": "terminal",
                "run_id": run_id,
                "final_status": status,
                "ended_at": 20.0,
            }
        )
    _jsonl(root / "outputs" / "_live" / "runs.jsonl", rows)
    return run_dir


def _write_package_record(root: Path, **extra):
    package = {
        "id": "pkg-1",
        "name": "Package",
        "category": "in-progress",
        "status": "BLOCKED",
        "currentBlocker": "waiting",
        "experiments": [
            {
                "id": "exp-1",
                "status": "queued",
                "sourceTask": "task-1",
            }
        ],
        **extra,
    }
    path = root / "research_html" / "data" / "research-packages.js"
    path.write_text(
        "window.RESEARCH_PACKAGES = "
        + json.dumps([package], sort_keys=True)
        + ";\n",
        encoding="utf-8",
    )


def test_shadow_migration_is_idempotent_and_preserves_semantics(tmp_path):
    _legacy_workspace(tmp_path)
    paths = ResearchPaths.resolve(workspace=tmp_path)
    first = migrate(paths)
    second = migrate(paths)
    assert first["events_added"] > 0
    assert second["events_added"] == 0
    assert first["gates"]["interface_rebuild"]["ok"] is True
    assert (paths.interface / "index.html").is_file()
    assert (paths.interface / "module.html").is_file()

    state = EventStore(paths).state()
    package = state["aggregates"]["package"]["pkg-1"]
    assert package["lifecycle"] == "ACTIVE"
    assert package["phase"] is None
    assert package["blocker"]["summary"] == "waiting"
    assert "plan.html" in package["interface_notes"]

    assert set(state["aggregates"]["experiment"]) == {"task-1"}
    experiment = state["aggregates"]["experiment"]["task-1"]
    assert experiment["local_id"] == "exp-1"
    assert experiment["aliases"] == ["task-1", "exp-1"]
    assert experiment["status"] == "READY"
    assert "after" not in experiment
    assert experiment["spec"]["purpose"] == "purpose"
    assert "after" not in experiment["spec"]

    assert "paper-1" in state["aggregates"]["paper"]
    assert "gap-1" in state["aggregates"]["knowledge_gap"]
    assert state["aggregates"]["proposal"]["proposal-1"]["disposition"] == "PENDING"
    idea = state["aggregates"]["brainstorm"]["idea-1"]
    assert idea["legacy_detail_path"] == "brainstorm/2026-06-03-idea-1.html"
    detail_note = paths.root / idea["detail_note"]["uri"]
    assert 'id="human-note"' in detail_note.read_text(encoding="utf-8")
    assert check(paths)["ok"] is True


def test_package_local_experiment_ids_do_not_collide(tmp_path):
    data = tmp_path / "research_html" / "data"
    data.mkdir(parents=True)
    (data / "research-packages.js").write_text(
        """
window.RESEARCH_PACKAGES = [
  {id: "pkg-a", category: "in-progress", status: "CONTEXT_LOADED",
   experiments: [{id: "P1", status: "queued"}]},
  {id: "pkg-b", category: "in-progress", status: "CONTEXT_LOADED",
   experiments: [{id: "P1", status: "queued"}]}
];
""",
        encoding="utf-8",
    )
    paths = ResearchPaths.resolve(workspace=tmp_path)
    migrate(paths)
    experiments = EventStore(paths).state()["aggregates"]["experiment"]

    assert set(experiments) == {"pkg-a::P1", "pkg-b::P1"}
    assert {row["local_id"] for row in experiments.values()} == {"P1"}


def test_scope_migration_preserves_all_transition_versions(tmp_path):
    _legacy_workspace(tmp_path)
    transition_path = tmp_path / "outputs" / "_scope" / "transitions.jsonl"
    rows = [
        json.loads(line)
        for line in transition_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows.append(
        {
            "transaction_id": "txn-task-2",
            "scope_version": 2,
            "op": "revise",
            "gate": "AGENT_DEFERRED_ACK",
            "node": {
                "id": "task-1",
                "level": "task",
                "parents": ["direction-1"],
                "version": 2,
                "status": "ACTIVE",
                "spec": {
                    "experiment": "revised purpose",
                    "config": "config-v2.yaml",
                    "gate": "metric >= 2",
                    "control_mode": "CHECKPOINTED",
                },
                "source": "test-v2",
            },
        }
    )
    _jsonl(transition_path, rows)
    paths = ResearchPaths.resolve(workspace=tmp_path)

    migrate(paths)

    experiment = EventStore(paths).state()["aggregates"]["experiment"]["task-1"]
    assert experiment["scope_version"] == 2
    assert experiment["spec"]["purpose"] == "revised purpose"
    assert [
        row["transaction_id"] for row in experiment["legacy_transitions"]
    ] == ["txn-1", "txn-task-2"]
    imported = [
        event
        for event in EventStore(paths).events()
        if event["aggregate_type"] == "experiment"
        and event["aggregate_id"] == "task-1"
        and event["event_type"] == "AggregateImported"
    ]
    assert [
        len(event["payload"]["record"]["legacy_transitions"])
        for event in imported
    ] == [1, 2, 2]
    projected = [
        json.loads(line)
        for line in (
            paths.interface / "data" / "scope-transitions.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    task_history = [
        row for row in projected if row.get("node_id") == "task-1"
    ]
    assert [row["node"]["version"] for row in task_history] == [1, 2]
    assert {
        row["node"]["level"] for row in task_history
    } == {"experiment"}


def test_allocation_uses_scope_experiment_identity_not_package_alias(tmp_path):
    _legacy_workspace(tmp_path)
    resources = tmp_path / "outputs" / "_resources"
    resources.mkdir(parents=True)
    (resources / "servers.json").write_text("[]\n", encoding="utf-8")
    _jsonl(
        resources / "allocations.jsonl",
        [
            {
                "op": "allocate",
                "alloc_id": "alloc-1",
                "server": "local",
                "pkg": "pkg-1",
                "exp_id": "exp-1",
                "gpu_count": 0,
            }
        ],
    )
    paths = ResearchPaths.resolve(workspace=tmp_path)

    migrate(paths)

    allocation = EventStore(paths).state()["aggregates"][
        "resource_allocation"
    ]["alloc-1"]
    assert allocation["experiment_id"] == "task-1"
    assert allocation["experiment_local_id"] == "exp-1"


def test_terminal_run_is_mechanically_copied_and_meta_becomes_run_json(tmp_path):
    _legacy_workspace(tmp_path)
    source = _legacy_run(tmp_path, status="COMPLETED")
    (tmp_path / "outputs" / "pkg-1" / "context_pack.json").write_text(
        '{"package":{"id":"pkg-1"},"rules":[{"id":"R1"}]}\n',
        encoding="utf-8",
    )
    paths = ResearchPaths.resolve(workspace=tmp_path)

    report = migrate(paths)

    assert report["ok"] is True
    assert paths.version_file.read_text(encoding="utf-8") == "1\n"
    destination = paths.run_dir("pkg-1", "exp-1", "run-1")
    assert not (destination / "meta.json").exists()
    assert (destination / "log.txt").read_text(encoding="utf-8") == "measured\n"
    run = json.loads((destination / "run.json").read_text(encoding="utf-8"))
    original = json.loads((source / "meta.json").read_text(encoding="utf-8"))
    assert run["experiment_id"] == "task-1"
    assert run["experiment_local_id"] == "exp-1"
    assert run["legacy"]["meta"] == original
    assert run["legacy_path"] == "outputs/pkg-1/runs/run-1"
    assert len(run["legacy"]["meta_sha256"]) == 64
    assert len(run["legacy"]["source_tree_sha256"]) == 64
    context = json.loads((destination / "context.json").read_text(encoding="utf-8"))
    result = json.loads((destination / "result.json").read_text(encoding="utf-8"))
    assert context["data"]["legacy_context_pack"]["json"]["package"]["id"] == "pkg-1"
    assert context["selected_experiment_id"] == "task-1"
    assert result["experiment_id"] == "task-1"
    verify_run_files(run, context)
    verify_result_evidence(paths, run, result)
    migrated = EventStore(paths).state()["aggregates"]["run"]["run-1"]
    assert migrated["dir"] == "experiments/pkg-1/exp-1/run-1"
    assert migrated["experiment_id"] == "task-1"
    assert migrated["status"] == "COMPLETED"
    assert migrated["terminal_event_id"]
    assert migrated["result_finalized_event_id"]
    finalized = migrated["latest_scientific_result"]
    assert finalized["verdict"] == "INCONCLUSIVE"
    assert finalized["validity"] == "UNMEASURED"
    assert finalized["supported_claims"] == []
    assert finalized["unsupported_claims"] == []
    assert finalized["result_sha256"] == hashlib.sha256(
        (destination / "result.json").read_bytes()
    ).hexdigest()
    run_events = [
        event["event_type"]
        for event in EventStore(paths).events()
        if event["aggregate_type"] == "run"
        and event["aggregate_id"] == "run-1"
    ]
    assert run_events == [
        "RunLaunchAuthorized",
        "RunLaunched",
        "RunTerminal",
        "RunResultFinalized",
    ]
    reconciled = reconcile_runs(paths)
    assert reconciled.scanned == 1
    assert reconciled.errors == ()
    assert reconciled.actions == ()
    assert report["run_migrations"][0]["destination_tree_sha256"]
    assert report["run_migrations"][0]["context_json_sha256"]
    assert report["run_migrations"][0]["result_json_sha256"]
    assert check(paths)["ok"] is True

    second = migrate(paths)
    assert second["events_added"] == 0
    assert second["already_current"] is True


def test_semantic_facts_canonicalize_only_with_typed_owners_and_run_evidence(
    tmp_path,
):
    _legacy_workspace(tmp_path)
    source = _legacy_run(tmp_path, status="COMPLETED")
    legacy_result = source / "result.json"
    legacy_result.write_text(
        json.dumps(
            {
                "protocol": {"kind": "legacy-test"},
                "measurements": {"accuracy": 0.9},
                "verdict": "PASS",
                "validity": "VALID",
                "supported_claims": ["Accuracy reached the recorded gate."],
                "unsupported_claims": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    result_uri = legacy_result.relative_to(tmp_path).as_posix()
    result_sha256 = hashlib.sha256(legacy_result.read_bytes()).hexdigest()
    _write_package_record(
        tmp_path,
        methodsTried=[
            {
                "id": "method-1",
                "exp_id": "exp-1",
                "run_id": "run-1",
                "method": "candidate",
                "metric": "accuracy",
                "measured": "0.9",
                "verdict": "PASS",
                "validity": "VALID",
                "evidencePath": result_uri,
                "result_sha256": result_sha256,
            }
        ],
        resultGateRows=[],
        resultBlocks=[],
        analysisInsights=[
            {
                "id": "insight-1",
                "title": "Measured insight",
                "lead": "The recorded run reached the gate.",
                "evidence": [
                    {
                        "run_id": "run-1",
                        "uri": result_uri,
                        "sha256": result_sha256,
                    }
                ],
            }
        ],
        implementation={
            "changes": [
                {
                    "id": "change-1",
                    "owned_files": ["train.py"],
                    "review": {"status": "PASS", "summary": "Reviewed"},
                    "validating_experiments": ["exp-1"],
                }
            ]
        },
        acknowledgements=[
            {
                "id": "ack-1",
                "ack_type": "scope",
                "value": "ACKNOWLEDGED",
                "actor": {"type": "system", "id": "legacy-controller"},
                "evidence": [
                    {
                        "kind": "NOTE",
                        "uri": "legacy://explicit-ack",
                        "sha256": "a" * 64,
                    }
                ],
            }
        ],
    )
    tables = (
        tmp_path
        / "research_html"
        / "data"
        / "packages"
        / "pkg-1"
        / "tables"
    )
    tables.mkdir(parents=True)
    (tables / "result_gate.csv").write_text(
        "row_id,exp_id,run_id,metric,value,verdict,validity,"
        "source_artifact,result_sha256\n"
        f"gate-1,exp-1,run-1,accuracy,0.9,PASS,VALID,"
        f"{result_uri},{result_sha256}\n",
        encoding="utf-8",
    )
    paths = ResearchPaths.resolve(workspace=tmp_path)

    report = migrate(paths)

    assert report["ok"] is True
    gate = report["gates"]["semantic_fact_migration"]
    assert gate["ok"] is True
    assert gate["counts"]["canonicalized"] == 5
    assert gate["counts"]["unresolved"] == 0
    state = EventStore(paths).state()
    package = state["aggregates"]["package"]["pkg-1"]
    for field in (
        "methodsTried",
        "resultGateRows",
        "resultBlocks",
        "analysisInsights",
        "implementationReviews",
        "acknowledgements",
    ):
        assert field not in package
    assert "implementation" not in package
    learning = state["aggregates"]["learning"][
        "pkg-1::learning::insight-1"
    ]
    assert learning["evidence"][0]["run_id"] == "run-1"
    assert learning["evidence"][0]["result_sha256"]
    change = state["aggregates"]["change"]["pkg-1::change::change-1"]
    assert change["validating_experiments"] == ["task-1"]
    decision = state["aggregates"]["decision"]["pkg-1::ack::ack-1"]
    assert decision["actor"] == {
        "type": "system",
        "id": "legacy-controller",
    }
    assert state["aggregates"]["run"]["run-1"][
        "latest_scientific_result"
    ]["measurements"] == {"accuracy": 0.9}
    dispositions = {
        (row["fact_kind"], row["row_id"]): row["disposition"]
        for row in report["semantic_fact_ledger"]
    }
    assert dispositions[("package.methodsTried", "method-1")] == "canonicalized"
    assert dispositions[("csv.result_gate", "gate-1")] == "canonicalized"
    manifest = json.loads(
        (paths.state / "migration.json").read_text(encoding="utf-8")
    )
    assert manifest["semantic_fact_ledger"] == report["semantic_fact_ledger"]
    assert check(paths)["ok"] is True


def test_measured_fact_without_terminal_run_blocks_version(tmp_path):
    _legacy_workspace(tmp_path)
    tables = (
        tmp_path
        / "research_html"
        / "data"
        / "packages"
        / "pkg-1"
        / "tables"
    )
    tables.mkdir(parents=True)
    (tables / "result_gate.csv").write_text(
        "row_id,exp_id,metric,value,verdict,validity,source_artifact\n"
        "gate-1,exp-1,accuracy,0.9,PASS,VALID,"
        "outputs/pkg-1/exp-1/result.json\n",
        encoding="utf-8",
    )
    paths = ResearchPaths.resolve(workspace=tmp_path)

    report = migrate(paths)

    assert report["ok"] is False
    assert not paths.version_file.exists()
    assert report["gates"]["semantic_fact_migration"]["ok"] is False
    assert any(
        blocker["code"] == "UNRESOLVED_LEGACY_SEMANTIC_FACT"
        and blocker["fact_kind"] == "csv.result_gate"
        and blocker["row_id"] == "gate-1"
        for blocker in report["blockers"]
    )


def test_structured_ack_without_actor_blocks_and_html_is_not_inferred(tmp_path):
    _legacy_workspace(tmp_path)
    _write_package_record(
        tmp_path,
        acknowledgements=[
            {
                "id": "ack-missing-actor",
                "ack_type": "scope",
                "value": "ACKNOWLEDGED",
                "evidence": [{"kind": "NOTE", "uri": "legacy://ack"}],
            }
        ],
    )
    tracker = (
        tmp_path
        / "research_html"
        / "packages"
        / "pkg-1"
        / "tracker.html"
    )
    tracker.write_text(
        '<html><body><div data-ack="scope" '
        'data-ack-value="ACKNOWLEDGED"></div></body></html>\n',
        encoding="utf-8",
    )
    paths = ResearchPaths.resolve(workspace=tmp_path)

    report = migrate(paths)

    assert report["ok"] is False
    assert not paths.version_file.exists()
    assert any(
        blocker["code"] == "UNRESOLVED_LEGACY_SEMANTIC_FACT"
        and blocker["fact_kind"] == "package.acknowledgements"
        and "actor" in blocker["reason"]
        for blocker in report["blockers"]
    )
    state = EventStore(paths, migration_mode=True).state()
    assert not any(
        decision.get("ack_type") == "scope"
        for decision in state["aggregates"]["decision"].values()
        if isinstance(decision, dict)
    )


def test_active_run_is_deferred_and_version_waits_until_it_is_terminal(tmp_path):
    _legacy_workspace(tmp_path)
    source = _legacy_run(tmp_path, status="RUNNING")
    paths = ResearchPaths.resolve(workspace=tmp_path)

    blocked = migrate(paths)

    assert blocked["ok"] is False
    assert blocked["status"] == "blocked"
    assert not paths.version_file.exists()
    assert any(
        item["code"] == "ACTIVE_LEGACY_RUN" for item in blocked["blockers"]
    )
    assert not paths.run_dir("pkg-1", "exp-1", "run-1").exists()
    # The legacy run remains in place and can continue writing.
    assert (source / "meta.json").exists()

    status = json.loads((source / "status.json").read_text(encoding="utf-8"))
    status["status"] = "COMPLETED"
    status["ended_at"] = 20.0
    (source / "status.json").write_text(json.dumps(status), encoding="utf-8")
    _jsonl(
        tmp_path / "outputs" / "_live" / "runs.jsonl",
        [
            {
                "op": "launched",
                "run_id": "run-1",
                "pkg": "pkg-1",
                "exp_id": "exp-1",
                "dir": str(source),
                "started_at": 10.0,
            },
            {
                "op": "terminal",
                "run_id": "run-1",
                "final_status": "COMPLETED",
                "ended_at": 20.0,
            },
        ],
    )

    complete = migrate(paths)
    assert complete["ok"] is True
    assert complete["version_finalized"] is True
    assert paths.version_file.exists()
    assert paths.run_dir("pkg-1", "exp-1", "run-1").exists()


def test_missing_experiment_id_is_reported_without_guessing_or_version(tmp_path):
    _legacy_workspace(tmp_path)
    _legacy_run(tmp_path, status="COMPLETED", experiment_id=None)
    paths = ResearchPaths.resolve(workspace=tmp_path)

    report = migrate(paths)

    assert report["ok"] is False
    assert not paths.version_file.exists()
    assert any(
        item["code"] == "MISSING_EXPERIMENT_ID"
        for item in report["blockers"]
    )
    assert report["run_migrations"] == []


def test_unknown_run_experiment_alias_blocks_version_without_dangling_ref(
    tmp_path,
):
    _legacy_workspace(tmp_path)
    _legacy_run(tmp_path, status="COMPLETED", experiment_id="unknown-exp")
    paths = ResearchPaths.resolve(workspace=tmp_path)

    report = migrate(paths)

    assert report["ok"] is False
    assert not paths.version_file.exists()
    assert any(
        item["code"] == "UNKNOWN_EXPERIMENT_ID"
        and item["run_id"] == "run-1"
        for item in report["blockers"]
    )
    assert "run-1" not in EventStore(paths, migration_mode=True).state()[
        "aggregates"
    ]["run"]
    assert report["run_migrations"] == []


def test_parity_failure_cannot_publish_version(tmp_path, monkeypatch):
    _legacy_workspace(tmp_path)
    paths = ResearchPaths.resolve(workspace=tmp_path)
    real_parity = migration._import_parity

    def fail_parity(*args, **kwargs):
        result = real_parity(*args, **kwargs)
        result["ok"] = False
        result["missing"] = [{"identity": "planted"}]
        return result

    monkeypatch.setattr(migration, "_import_parity", fail_parity)
    report = migrate(paths)

    assert report["ok"] is False
    assert not paths.version_file.exists()
    assert any(
        item["code"] == "IMPORT_PARITY_FAILED"
        for item in report["blockers"]
    )


def test_interface_rebuild_failure_cannot_publish_version(tmp_path, monkeypatch):
    _legacy_workspace(tmp_path)
    paths = ResearchPaths.resolve(workspace=tmp_path)

    monkeypatch.setattr(
        migration,
        "_build_migration_interface",
        lambda *_args, **_kwargs: {
            "ok": False,
            "status": "failed",
            "files_written": 0,
            "missing": ["module.html"],
            "source_matches": False,
            "error": "planted renderer failure",
        },
    )
    report = migrate(paths)

    assert report["ok"] is False
    assert report["gates"]["interface_rebuild"]["ok"] is False
    assert not paths.version_file.exists()
    assert any(
        item["code"] == "INTERFACE_REBUILD_FAILED"
        for item in report["blockers"]
    )


def test_frozen_interface_failure_cannot_publish_version(tmp_path, monkeypatch):
    _legacy_workspace(tmp_path)
    paths = ResearchPaths.resolve(workspace=tmp_path)
    monkeypatch.setattr(
        migration,
        "_frozen_interface_contract_gate",
        lambda: {
            "ok": False,
            "status": "failed",
            "error": "planted frozen contract failure",
        },
    )

    report = migrate(paths)

    assert report["ok"] is False
    assert not paths.version_file.exists()
    assert report["gates"]["frozen_interface_contract"]["ok"] is False
    assert any(
        item["code"] == "INTERFACE_FROZEN_CONTRACT_FAILED"
        for item in report["blockers"]
    )
    assert not any(
        item["code"] == "INTERFACE_REBUILD_FAILED"
        for item in report["blockers"]
    )


def test_legacy_dom_drift_cannot_publish_version(tmp_path, monkeypatch):
    _legacy_workspace(tmp_path)
    paths = ResearchPaths.resolve(workspace=tmp_path)
    monkeypatch.setattr(
        migration,
        "_frozen_interface_contract_gate",
        lambda: {"ok": True, "status": "passed"},
    )
    monkeypatch.setattr(
        migration,
        "_legacy_interface_dom_gate",
        lambda _paths: {
            "ok": False,
            "status": "failed",
            "drift": [{"path": "packages/pkg-1/plan.html"}],
        },
    )

    report = migrate(paths)

    assert report["ok"] is False
    assert not paths.version_file.exists()
    assert report["gates"]["legacy_interface_dom_parity"]["ok"] is False
    assert any(
        item["code"] == "LEGACY_INTERFACE_DOM_PARITY_FAILED"
        for item in report["blockers"]
    )
    assert not any(
        item["code"] == "INTERFACE_REBUILD_FAILED"
        for item in report["blockers"]
    )


def test_authority_inventory_classifies_and_imports_all_legacy_store_families(
    tmp_path,
):
    _legacy_workspace(tmp_path)
    data = tmp_path / "research_html" / "data" / "packages"
    data.mkdir(parents=True)
    (data / "pkg-1.facts.js").write_text(
        'window.PACKAGE_FACTS = window.PACKAGE_FACTS || {};\n'
        'window.PACKAGE_FACTS["pkg-1"] = {'
        '"pages":{"results":{"summary":"kept"}},'
        '"resultSchemas":{"schema-exp-1":{"id":"schema-exp-1",'
        '"expId":"exp-1","tableId":"table-exp-1"}},'
        '"resultTables":["table-exp-1"]};\n',
        encoding="utf-8",
    )
    tables = data / "pkg-1" / "tables"
    tables.mkdir(parents=True)
    (tables / "result_gate.csv").write_text(
        "row_id,exp_id,metric,value,verdict,validity\n"
        "exp-1-gate,exp-1,accuracy,unmeasured,,UNMEASURED\n",
        encoding="utf-8",
    )

    package_output = tmp_path / "outputs" / "pkg-1"
    package_output.mkdir(parents=True)
    (package_output / "context_pack.json").write_text(
        '{"package":{"id":"pkg-1"}}\n',
        encoding="utf-8",
    )
    (package_output / "context_pack.md").write_text(
        "# Derived context\n",
        encoding="utf-8",
    )
    manifests = package_output / "manifests"
    manifests.mkdir()
    (manifests / "terminal.json").write_text(
        '{"event":"TERMINAL_TRANSITION"}\n',
        encoding="utf-8",
    )
    (manifests / "terminal.json.applied").write_text("", encoding="utf-8")

    brainstorm = tmp_path / "outputs" / "_brainstorm" / "round-1"
    (brainstorm / "verdicts").mkdir(parents=True)
    (brainstorm / "candidates.json").write_text(
        '[{"id":"candidate-1","title":"Candidate"}]\n',
        encoding="utf-8",
    )
    (brainstorm / "verdicts" / "rank-1.json").write_text(
        '{"ranking_id":"rank-1","ranking":["candidate-1"]}\n',
        encoding="utf-8",
    )

    learned = tmp_path / "outputs" / "_learned"
    learned.mkdir()
    (learned / "rules.md").write_text(
        "# Rules\n\n- Never compare metrics with different splits.\n",
        encoding="utf-8",
    )

    selfevolve = tmp_path / "outputs" / "_selfevolve"
    rule_path = selfevolve / "rules" / "candidates" / "rule-se" / "1" / "rule.json"
    rule_path.parent.mkdir(parents=True)
    rule_path.write_text(
        json.dumps(
            {
                "id": "rule-se",
                "version": "1",
                "title": "Rule",
                "scope": {"packages": ["*"]},
            }
        ),
        encoding="utf-8",
    )
    _jsonl(
        selfevolve / "rules" / "transitions.jsonl",
        [
            {
                "transition_id": "trn-rule-se",
                "store": "rule",
                "entity_id": "rule-se",
                "entity_version": "1",
                "to_state": "RULE_ACTIVE",
            }
        ],
    )
    _jsonl(
        selfevolve / "events" / "events.jsonl",
        [{"event_id": "observation-1", "type": "user-correction"}],
    )
    _jsonl(
        selfevolve / "approvals" / "approvals.jsonl",
        [{"approval_id": "approval-1", "decision": "APPROVED"}],
    )
    evidence = selfevolve / "evidence" / "rule-se" / "1" / "oracle.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        '{"evidence_id":"oracle-1","oracle":{"result":"ORACLE_PASS"}}\n',
        encoding="utf-8",
    )
    skill = selfevolve / "skills" / "candidates" / "skill-1" / "1" / "manifest.json"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        '{"id":"skill-1","version":"1","description":"legacy"}\n',
        encoding="utf-8",
    )

    report = inventory(tmp_path)

    assert not (tmp_path / ".research").exists()
    assert report["authority"]["complete"] is True
    classifications = {
        item["classification"] for item in report["authority"]["files"]
    }
    assert {
        "brainstorm-candidate-authority",
        "brainstorm-decision-authority",
        "learned-rule-authority",
        "selfevolve-authority",
        "package-fact-authority",
        "context-pack-projection",
        "consumed-package-manifest",
    } <= classifications
    assert all(
        report["authority"]["families"][name]["files"] > 0
        for name in (
            "brainstorm",
            "learned",
            "selfevolve",
            "package_facts",
            "package_manifests",
            "context_packs",
        )
    )

    migrated = migrate(ResearchPaths.resolve(workspace=tmp_path))
    assert migrated["ok"] is True
    semantic_gate = migrated["gates"]["semantic_fact_migration"]
    assert semantic_gate["ok"] is True
    assert semantic_gate["counts"]["derivable"] >= 2
    state = EventStore(ResearchPaths.resolve(workspace=tmp_path)).state()
    fact_files = state["aggregates"]["package"]["pkg-1"]["legacy_fact_store"]["files"]
    archive = state["aggregates"]["package"]["pkg-1"]["legacy_fact_store"]
    assert archive["role"] == "raw-provenance-archive"
    assert archive["authoritative"] is False
    assert fact_files["tables/result_gate.csv"]["data"][0]["value"] == "unmeasured"
    planned = state["aggregates"]["experiment"]["task-1"]["spec"][
        "result_schema"
    ]["legacy_rows"]
    assert any(
        row["kind"] == "csv.result_gate"
        and row["row"]["row_id"] == "exp-1-gate"
        for row in planned.values()
    )
    assert any(
        row["kind"] == "facts.result_schema"
        and row["row"]["id"] == "schema-exp-1"
        for row in planned.values()
    )
    assert state["aggregates"]["rule"]["rule-se@1"]["status"] == "ACTIVE"
    assert any(
        rule.get("origin") == "legacy-learned"
        for rule in state["aggregates"]["rule"].values()
    )
    assert "legacy-ranking:round-1:rank-1" in state["aggregates"]["decision"]
    assert "legacy-selfevolve:observation-1" in state["aggregates"]["learning"]
    assert "legacy-skill:skill-1@1" in state["aggregates"]["learning"]


def test_unclassified_authority_and_pending_manifest_block_version(tmp_path):
    _legacy_workspace(tmp_path)
    mystery = tmp_path / "outputs" / "_mystery" / "authority.jsonl"
    mystery.parent.mkdir(parents=True)
    mystery.write_text('{"fact":"cannot guess"}\n', encoding="utf-8")
    pending = tmp_path / "outputs" / "pkg-1" / "manifests" / "pending.json"
    pending.parent.mkdir(parents=True)
    pending.write_text('{"event":"ADOPTION"}\n', encoding="utf-8")
    paths = ResearchPaths.resolve(workspace=tmp_path)

    first = migrate(paths)
    brainstorms = tmp_path / "research_html" / "data" / "brainstorms.js"
    brainstorms.write_text(
        'window.BRAINSTORMS = [{id: "idea-1", title: "Changed after shadow import"}];\n',
        encoding="utf-8",
    )
    drifted = migrate(paths)
    second = migrate(paths)

    assert first["ok"] is False
    assert any(
        item["code"] == "IMPORT_PARITY_FAILED"
        and item["unexpected"]
        for item in drifted["blockers"]
    )
    assert second["ok"] is False
    assert second["events_added"] == 0
    assert not paths.version_file.exists()
    codes = {item["code"] for item in second["blockers"]}
    assert "UNCLASSIFIED_LEGACY_AUTHORITY" in codes
    assert "PENDING_LEGACY_MANIFEST" in codes
    assert second["inventory"]["authority"]["complete"] is False


def test_finalized_run_and_source_drift_fail_closed(tmp_path):
    _legacy_workspace(tmp_path)
    source = _legacy_run(tmp_path, status="COMPLETED")
    paths = ResearchPaths.resolve(workspace=tmp_path)
    migrate(paths)

    destination = paths.run_dir("pkg-1", "exp-1", "run-1")
    (destination / "log.txt").write_text("tampered\n", encoding="utf-8")
    result = check(paths)
    assert result["ok"] is False
    assert result["run_drift"]
    with pytest.raises(MigrationError, match="drift"):
        migrate(paths)

    # Restore destination and plant independent legacy-source drift.
    (destination / "log.txt").write_text("measured\n", encoding="utf-8")
    (source / "log.txt").write_text("legacy changed\n", encoding="utf-8")
    result = check(paths)
    assert result["ok"] is False
    assert result["source_drift"] is not None


def test_manifest_tamper_and_unknown_version_fail_closed(tmp_path):
    _legacy_workspace(tmp_path)
    paths = ResearchPaths.resolve(workspace=tmp_path)
    migrate(paths)
    manifest_path = paths.state / "migration.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "forged"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(MigrationError, match="manifest tamper"):
        check(paths)

    other = tmp_path / "unknown"
    (other / ".research").mkdir(parents=True)
    (other / ".research" / "VERSION").write_text("999\n", encoding="utf-8")
    unknown = ResearchPaths.resolve(workspace=other)
    with pytest.raises(UnsupportedResearchVersion):
        unknown.initialize()
    with pytest.raises(UnsupportedResearchVersion):
        migrate(unknown)
