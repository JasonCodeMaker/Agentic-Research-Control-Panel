"""Focused contracts for the state-backed research management facade."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from lib.experiments.launch import launch_run
from lib.interface.package import package_view_models
from lib.research_state import EventStore, ResearchPaths
from tests.scope_fixtures import (
    commit_accepted_scope,
    direction_node,
    experiment_node,
    project_node,
)


SCRIPTS = Path(__file__).resolve().parents[2] / "skills/research-op/scripts"
sys.path.insert(0, str(SCRIPTS))
import management  # noqa: E402
from lib.research_state.io import read_jsonl  # noqa: E402


ACTOR = {"type": "agent", "id": "test"}
USER = {"type": "user", "id": "test-user"}
DIRECTION_ID = "dir/retrieval-v2"
EXPERIMENT_ID = "experiment/retrieval-v2/M0-baseline-validity"


def _evolution_ref() -> dict[str, object]:
    return {
        "uri": "experiments/pkg/P0/run/result.json",
        "sha256": "e" * 64,
        "size_bytes": 8,
        "kind": "FILE",
        "package_id": "pkg",
        "experiment_id": EXPERIMENT_ID,
        "run_id": "run",
    }


def _create(paths: ResearchPaths, *, phase: str) -> EventStore:
    for node in (
        project_node(),
        direction_node(node_id=DIRECTION_ID),
        experiment_node(node_id=EXPERIMENT_ID, parent=DIRECTION_ID),
    ):
        commit_accepted_scope(management, paths, node, actor=ACTOR)
    store = EventStore(paths)
    direction_event = next(
        event
        for event in reversed(store.events())
        if event["aggregate_type"] == "direction"
        and event["aggregate_id"] == DIRECTION_ID
    )
    accepted_experiment = store.state()["aggregates"]["experiment"][EXPERIMENT_ID]
    management.commit_package_create(
        paths,
        {
            "id": "pkg",
            "lifecycle": "ACTIVE",
            "phase": "CONTEXT_LOADED",
            "blocker": None,
            "hypothesis": "loss decreases",
            "direction_id": DIRECTION_ID,
            "sourceDirection": DIRECTION_ID,
            "sourceVersion": 1,
            "sourceChange": direction_event["event_id"],
            "sourceExperiments": [
                {
                    "id": EXPERIMENT_ID,
                    "version": accepted_experiment["scope_version"],
                    "source": accepted_experiment["scope_source"],
                }
            ],
        },
        [
            {
                "scope_experiment_id": EXPERIMENT_ID,
                "local_id": "P0",
                "status": "READY",
            }
        ],
        actor=ACTOR,
    )
    if phase != "CONTEXT_LOADED":
        package_version = store.state()["aggregate_versions"]["package/pkg"]
        store.commit(
            event_type="PackageMutationApplied",
            aggregate_type="package",
            aggregate_id="pkg",
            payload={
                "operation": "test-fixture",
                "target": "status",
                "operations": [
                    {
                        "operation": "set",
                        "target": "phase",
                        "value": phase,
                    }
                ],
            },
            actor=ACTOR,
            idempotency_key=f"test-fixture:package-phase:{phase}",
            expected_version=package_version,
            entry_skill="tests",
        )
    return store


def test_competing_package_materializations_cannot_leave_an_orphan_package(
    tmp_path,
):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    for node in (
        project_node(),
        direction_node(node_id=DIRECTION_ID),
        experiment_node(node_id=EXPERIMENT_ID, parent=DIRECTION_ID),
    ):
        commit_accepted_scope(management, paths, node, actor=ACTOR)
    store = EventStore(paths)
    direction_event = next(
        event
        for event in reversed(store.events())
        if event["aggregate_type"] == "direction"
        and event["aggregate_id"] == DIRECTION_ID
    )
    accepted = store.state()["aggregates"]["experiment"][EXPERIMENT_ID]
    barrier = threading.Barrier(2)

    def materialize(package_id):
        package = {
            "id": package_id,
            "lifecycle": "ACTIVE",
            "phase": "CONTEXT_LOADED",
            "blocker": None,
            "direction_id": DIRECTION_ID,
            "sourceVersion": 1,
            "sourceChange": direction_event["event_id"],
            "sourceExperiments": [
                {
                    "id": EXPERIMENT_ID,
                    "version": accepted["scope_version"],
                    "source": accepted["scope_source"],
                }
            ],
        }
        barrier.wait()
        try:
            management.commit_package_create(
                paths,
                package,
                [
                    {
                        "scope_experiment_id": EXPERIMENT_ID,
                        "local_id": "P0",
                        "status": "READY",
                    }
                ],
                actor=ACTOR,
            )
            return ("committed", package_id)
        except Exception as exc:
            return ("rejected", getattr(exc, "rule", type(exc).__name__))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(materialize, ("pkg-a", "pkg-b")))

    assert [status for status, _ in outcomes].count("committed") == 1
    assert [status for status, _ in outcomes].count("rejected") == 1
    state = store.state()
    assert len(state["aggregates"]["package"]) == 1
    winner = next(iter(state["aggregates"]["package"]))
    assert state["aggregates"]["experiment"][EXPERIMENT_ID]["package_id"] == winner
    materializations = [
        event
        for event in store.events()
        if event["event_type"] == "PackageMaterialized"
    ]
    assert len(materializations) == 1
    assert not any(
        event["event_type"] == "ExperimentBoundToPackage"
        for event in store.events()
    )
    binding = materializations[0]["payload"]["experiment_bindings"][0]
    assert binding["aggregate_id"] == EXPERIMENT_ID
    assert (
        state["aggregate_versions"][f"experiment/{EXPERIMENT_ID}"]
        == binding["aggregate_version"]
    )


def test_package_creation_cannot_start_at_a_privileged_phase(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="CONTEXT_LOADED")
    existing = store.state()["aggregates"]["package"]["pkg"]
    attempted = {
        **existing,
        "id": "privileged-start",
        "phase": "READY_TO_LAUNCH",
    }

    with pytest.raises(Exception) as rejected:
        management.commit_package_create(
            paths,
            attempted,
            [],
            actor=ACTOR,
        )

    assert getattr(rejected.value, "rule", "") == "package-initial-state-invalid"


def test_ready_to_launch_requires_an_independent_change_review(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="IMPLEMENTATION_REVIEW")

    with pytest.raises(Exception) as rejected:
        management.apply_package_operation(
            paths,
            "pkg",
            operation="update",
            target="status",
            payload={"to": "READY_TO_LAUNCH"},
            actor=ACTOR,
        )
    assert getattr(rejected.value, "rule", "") == "launch-review-required"

    review = management.commit_change_operation(
        paths,
        "pkg",
        "insert",
        {
            "change_id": "launch-review",
            "owned_files": ["src/model.py"],
            "validating_experiments": ["P0"],
            "review": {
                "producer": "codex",
                "judge": "claude-fable-5",
                "result": "SOUND",
                "summary": "The implementation matches the accepted plan.",
            },
        },
        actor=ACTOR,
    )
    event = management.apply_package_operation(
        paths,
        "pkg",
        operation="update",
        target="status",
        payload={
            "to": "READY_TO_LAUNCH",
            "review_change_id": "launch-review",
        },
        actor=ACTOR,
    )[0]

    package = store.state()["aggregates"]["package"]["pkg"]
    assert package["phase"] == "READY_TO_LAUNCH"
    assert package["reviewChangeId"] == "pkg::change::launch-review"
    assert event["causation_id"] == review["event_id"]


def test_terminal_success_requires_user_ack_and_bound_verifier_decision(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="RESULT_ANALYSIS")
    EventStore(paths, migration_mode=True).commit(
        event_type="AggregateImported",
        event_id="evt-finalized-result",
        aggregate_type="run",
        aggregate_id="run-success",
        payload={
            "record": {
                "id": "run-success",
                "package_id": "pkg",
                "experiment_id": EXPERIMENT_ID,
                "status": "COMPLETED",
                "result_finalized_event_id": "evt-finalized-result",
                "latest_scientific_result": {
                    "result_json": "experiments/pkg/P0/run-success/result.json",
                    "result_sha256": "a" * 64,
                    "verdict": "PASS",
                    "measured": 0.9,
                },
            }
        },
        actor=ACTOR,
        idempotency_key="import-finalized-result",
        expected_version=0,
    )

    with pytest.raises(Exception) as rejected:
        management.apply_package_operation(
            paths,
            "pkg",
            operation="update",
            target="status",
            payload={
                "to": "ADOPTED",
                "ack": "anything",
                "terminationMessage": "The gate passed.",
                "adoptionPath": "src/model.py",
            },
            actor=ACTOR,
        )
    assert getattr(rejected.value, "rule", "") == "terminal-decision-required"

    with pytest.raises(Exception) as rejected:
        management.commit_acknowledgement(
            paths,
            "pkg",
            {
                "ack_type": "TERMINAL_ACK",
                "to": "ACKNOWLEDGED",
                "target_status": "ADOPTED",
            },
            actor=ACTOR,
        )
    assert getattr(rejected.value, "rule", "") == "protected-ack-user-required"

    terminal_ack = management.commit_acknowledgement(
        paths,
        "pkg",
        {
            "id": "pkg::decision::terminal",
            "ack_type": "TERMINAL_ACK",
            "to": "ACKNOWLEDGED",
            "target_status": "ADOPTED",
        },
        actor=USER,
    )
    with pytest.raises(Exception) as rejected:
        management.apply_package_operation(
            paths,
            "pkg",
            operation="update",
            target="status",
            payload={
                "to": "ADOPTED",
                "terminationMessage": "The gate passed.",
                "adoptionPath": "src/model.py",
                "terminal_decision_id": "pkg::decision::terminal",
            },
            actor=ACTOR,
        )
    assert getattr(rejected.value, "rule", "") == "verifier-decision-required"

    verifier_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "research_op.py"),
            "--workspace",
            str(tmp_path),
            "--pkg",
            "pkg",
            "--op",
            "update",
            "--target",
            "results-verdict",
            "--payload",
            json.dumps(
                {
                    "id": "pkg::decision::verifier",
                    "run_id": "run-success",
                    "verdict": {
                        "producer": "codex",
                        "judge": "claude-fable-5",
                        "result": "SOUND",
                    },
                }
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (
        json.loads(verifier_result.stdout)["events"][0]["event_type"]
        == "DecisionRecorded"
    )
    terminal = management.apply_package_operation(
        paths,
        "pkg",
        operation="update",
        target="status",
        payload={
            "to": "ADOPTED",
            "terminationMessage": "The gate passed.",
            "adoptionPath": "src/model.py",
            "terminal_decision_id": "pkg::decision::terminal",
            "verifier_decision_id": "pkg::decision::verifier",
        },
        actor=ACTOR,
        idempotency_key="terminal-adopt",
    )[0]
    retried = management.apply_package_operation(
        paths,
        "pkg",
        operation="update",
        target="status",
        payload={
            "to": "ADOPTED",
            "terminationMessage": "The gate passed.",
            "adoptionPath": "src/model.py",
            "terminal_decision_id": "pkg::decision::terminal",
            "verifier_decision_id": "pkg::decision::verifier",
        },
        actor=ACTOR,
        idempotency_key="terminal-adopt",
    )[0]

    package = store.state()["aggregates"]["package"]["pkg"]
    assert package["lifecycle"] == "ADOPTED"
    assert package["terminationMessage"] == "The gate passed."
    assert package["adoptionPath"] == "src/model.py"
    assert package["terminalDecisionId"] == "pkg::decision::terminal"
    assert package["verifierDecisionId"] == "pkg::decision::verifier"
    assert terminal["causation_id"] == terminal_ack["event_id"]
    assert retried["event_id"] == terminal["event_id"]
    verifier_event = next(
        event
        for event in store.events()
        if event["aggregate_id"] == "pkg::decision::verifier"
    )
    assert verifier_event["causation_id"] == "evt-finalized-result"


def test_facade_rejection_before_domain_commit_is_audited(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})

    with pytest.raises(Exception) as rejected:
        management.commit_package_create(paths, {}, [])

    assert getattr(rejected.value, "rule", "") == "package-id-required"
    assert EventStore(paths).events() == []
    rows = [
        row
        for row in read_jsonl(paths.audit_actions)
        if row.get("aggregate_id") == "commit_package_create"
    ]
    assert [row["outcome"] for row in rows] == [
        "COMMAND_RECEIVED",
        "COMMAND_REJECTED",
    ]
    assert rows[-1]["rejection_reason"]["rule"] == "package-id-required"


def test_facade_rejection_audit_binds_names_and_summarizes_sensitive_text(
    tmp_path,
):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    secrets = {
        "content": "content-secret",
        "text": "text-secret",
        "note": "note-secret",
        "command": "python --token command-secret",
        "env": {"API_TOKEN": "env-secret"},
        "secret": "explicit-secret",
    }

    with pytest.raises(Exception):
        management.commit_package_create(paths, secrets, [])

    rows = [
        row
        for row in read_jsonl(paths.audit_actions)
        if row.get("aggregate_id") == "commit_package_create"
    ]
    assert [row["outcome"] for row in rows] == [
        "COMMAND_RECEIVED",
        "COMMAND_REJECTED",
    ]
    serialized = json.dumps(rows, sort_keys=True)
    for secret in (
        "content-secret",
        "text-secret",
        "note-secret",
        "command-secret",
        "env-secret",
        "explicit-secret",
    ):
        assert secret not in serialized
    record = rows[-1]["payload"]["parameters"]["record"]
    for field in ("content", "text", "note"):
        assert record[field] == {
            "kind": "redacted-argument",
            "size_bytes": len(secrets[field].encode("utf-8")),
            "sha256": hashlib.sha256(secrets[field].encode("utf-8")).hexdigest(),
        }
    for field in ("command", "env", "secret"):
        assert record[field] == "[REDACTED]"


def test_cli_level_rejection_is_audited(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    _create(paths, phase="RESULT_ANALYSIS")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "research_op.py"),
            "--workspace",
            str(tmp_path),
            "--pkg",
            "pkg",
            "--op",
            "update",
            "--target",
            "tracker-chosen-route",
            "--payload",
            "{}",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    rows = [
        row
        for row in read_jsonl(paths.audit_actions)
        if row.get("aggregate_id") == "research-op-cli"
    ]
    assert [row["outcome"] for row in rows[-2:]] == [
        "COMMAND_RECEIVED",
        "COMMAND_REJECTED",
    ]
    assert rows[-1]["rejection_reason"]["detail"] == (
        "tracker-chosen-route is insert-only"
    )


def test_management_facades_emit_semantic_events_and_package_projection(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="IMPLEMENTING")
    EventStore(paths, migration_mode=True).commit(
        event_type="AggregateImported",
        aggregate_type="run",
        aggregate_id="run",
        payload={
            "record": {
                "id": "run",
                "package_id": "pkg",
                "experiment_id": EXPERIMENT_ID,
                "experiment_local_id": "P0",
                "status": "COMPLETED",
                "result_finalized_event_id": "legacy-finalized",
                "latest_scientific_result": {
                    "result_json": "experiments/pkg/P0/run/result.json",
                    "result_sha256": "e" * 64,
                    "evidence": [
                        {
                            "uri": "experiments/pkg/P0/run/result.json",
                            "sha256": "e" * 64,
                        }
                    ],
                },
            }
        },
        actor=ACTOR,
        idempotency_key="seed-finalized-result",
    )
    cli = SCRIPTS / "research_op.py"
    cases = [
        (
            "insert",
            "analysis-insight",
            {
                "id": "stable-loss",
                "title": "Stable loss",
                "lead": "Observed pattern",
                "provenance": "experiments/pkg/P0/run/result.json",
            },
            ["LearningRecorded"],
        ),
        (
            "insert",
            "tracker-impl-review-row",
            {
                "change_id": "change-1",
                "status": "reviewed",
                "summary": "bounded change",
                "owned_files": ["src/model.py"],
                "validating_experiments": ["P0"],
            },
            ["AggregateUpserted"],
        ),
        (
            "update",
            "approval-ack-slot",
            {
                "ack_type": "scope",
                "to": "ACKNOWLEDGED",
                "page": "overview",
            },
            ["DecisionRecorded"],
        ),
    ]
    for operation, target, payload, expected in cases:
        result = subprocess.run(
            [
                sys.executable,
                str(cli),
                "--workspace",
                str(tmp_path),
                "--pkg",
                "pkg",
                "--op",
                operation,
                "--target",
                target,
                "--payload",
                json.dumps(payload),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        output = json.loads(result.stdout)
        assert [event["event_type"] for event in output["events"]] == expected
        assert output["interface_written"] is True
        assert output["interface_source_seq"] == len(store.events())

    state = store.state()
    assert len(state["aggregates"]["learning"]) == 1
    assert len(state["aggregates"]["change"]) == 1
    assert any(
        record.get("kind") == "ACKNOWLEDGEMENT"
        for record in state["aggregates"]["decision"].values()
    )
    package = state["aggregates"]["package"]["pkg"]
    assert "analysisInsights" not in package
    assert "implementationReviews" not in package
    assert "acknowledgements" not in package
    projected = package_view_models(state)[0]
    assert len(projected["analysisInsights"]) == 1
    assert len(projected["implementationReviews"]) == 1
    assert len(projected["acknowledgements"]) == 1
    assert projected["implementation"]["changes"][0]["codeAnchors"] == [
        "src/model.py"
    ]
    assert projected["implementation"]["changes"][0]["validatingExp"] == (
        EXPERIMENT_ID
    )
    assert (paths.interface / "packages/pkg/analysis.html").is_file()
    rendered = [
        json.loads(line)
        for line in paths.audit_actions.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["outcome"] == "PROJECTION_RENDERED"
    ]
    assert rendered
    assert rendered[-1]["domain_event_id"] == store.events()[-1]["event_id"]


def test_self_evolve_events_use_typed_management_gateways(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    scope = {
        "project": "project/main",
        "packages": ["*"],
        "task_types": ["metric-change"],
    }
    learning_id = "learning:rule.metric@1"
    management.commit_evolution_learning(
        paths,
        {
            "id": learning_id,
            "observation": "Metric changes need evidence.",
            "scope": scope,
            "evidence_refs": [_evolution_ref()],
        },
        idempotency_key="learning:rule.metric",
    )
    management.commit_evolution_decision(
        paths,
        {
            "id": "decision:promote",
            "decision_type": "ADMISSION",
            "subject_id": learning_id,
            "admission": "FULLY_ADMITTED",
            "evidence_refs": [_evolution_ref()],
        },
        idempotency_key="decision:promote",
    )
    management.commit_evolution_rule_promotion(
        paths,
        learning_id=learning_id,
        decision_id="decision:promote",
        rule={
            "id": "rule.metric",
            "version": "1",
            "content": "Verify every metric change.",
            "scope": scope,
        },
        idempotency_key="promote:rule.metric",
    )
    management.commit_evolution_decision(
        paths,
        {
            "id": "decision:retire",
            "decision_type": "RULE_LIFECYCLE",
            "subject_id": "rule.metric@1",
            "outcome": "INVALIDATED",
            "evidence_refs": [_evolution_ref()],
        },
        idempotency_key="decision:retire",
    )
    management.commit_evolution_rule_retirement(
        paths,
        rule_id="rule.metric",
        version="1",
        decision_id="decision:retire",
        lifecycle_state="INVALIDATED",
        idempotency_key="retire:rule.metric",
    )

    events = EventStore(paths).events()
    assert [event["event_type"] for event in events] == [
        "LearningRecorded",
        "DecisionRecorded",
        "RulePromoted",
        "DecisionRecorded",
        "RuleRetired",
    ]
    audit = [
        json.loads(line)
        for line in paths.audit_actions.read_text(encoding="utf-8").splitlines()
        if line
    ]
    committed = [
        row
        for row in audit
        if row["outcome"] == "COMMAND_COMMITTED"
    ]
    assert {row["entry_skill"] for row in committed} == {
        "research-op/self-evolve"
    }
    state = EventStore(paths).state()
    rule = state["aggregates"]["rule"]["rule.metric@1"]
    assert rule["origin"] == "selfevolve"
    assert rule["status"] == "RETIRED"
    assert rule["lifecycle_state"] == "INVALIDATED"
    assert rule["evidence_refs"] == [_evolution_ref()]


def test_approval_ack_slot_launch_ack_authorizes_launcher(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="READY_TO_LAUNCH")
    cli = SCRIPTS / "research_op.py"
    acknowledgement = subprocess.run(
        [
            sys.executable,
            str(cli),
            "--workspace",
            str(tmp_path),
            "--pkg",
            "pkg",
            "--op",
            "update",
            "--target",
            "approval-ack-slot",
            "--actor-type",
            "user",
            "--actor-id",
            USER["id"],
            "--payload",
            json.dumps(
                {
                    "ack_type": "LAUNCH_ACK",
                    "to": "ACKNOWLEDGED",
                    "experiment_id": "P0",
                    "page": "overview",
                }
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    output = json.loads(acknowledgement.stdout)
    decision_event = output["events"][0]
    decision_id = decision_event["aggregate"].split("/", 1)[1]
    decision = store.state()["aggregates"]["decision"][
        decision_id
    ]
    assert decision["kind"] == "LAUNCH_ACK"
    assert decision["experiment_id"] == EXPERIMENT_ID
    assert decision["actor"] == USER

    result = launch_run(
        paths=paths,
        package_id="pkg",
        experiment_id=EXPERIMENT_ID,
        run_id="ack-slot-launch",
        command=[sys.executable, "-c", "print('ok')"],
        cwd=tmp_path,
        environment={},
        use_tmux=False,
    )
    run = json.loads(result.run_path.read_text(encoding="utf-8"))
    assert result.status == "COMPLETED"
    assert run["launch_ack_decision_id"] == decision["id"]


def test_launch_ack_never_infers_a_user_actor(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="READY_TO_LAUNCH")
    before = len(store.events())

    with pytest.raises(Exception) as rejected:
        management.commit_acknowledgement(
            paths,
            "pkg",
            {
                "ack_type": "LAUNCH_ACK",
                "to": "ACKNOWLEDGED",
                "experiment_id": "P0",
            },
            actor=None,
        )

    assert getattr(rejected.value, "rule", "") == "launch-ack-user-required"
    assert len(store.events()) == before


def test_decision_facades_are_retry_stable_and_identity_immutable(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="NEXT_ACTION_READY")
    payload = {
        "id": "pkg::decision::next",
        "route": "RUN_NEXT_EXPERIMENT",
        "evidence": [{"kind": "REFERENCE", "uri": "note://adjudication"}],
    }
    first = management.commit_decision(
        paths,
        "pkg",
        payload,
        actor=ACTOR,
        idempotency_key="decision:next",
    )
    retried = management.commit_decision(
        paths,
        "pkg",
        payload,
        actor=ACTOR,
        idempotency_key="decision:next",
    )
    assert retried["event_id"] == first["event_id"]

    with pytest.raises(Exception) as rejected:
        management.commit_decision(
            paths,
            "pkg",
            {
                **payload,
                "route": "TERMINATE",
            },
            actor=ACTOR,
            idempotency_key="decision:next:replacement",
        )
    assert getattr(rejected.value, "rule", "") == "decision-immutable"
    assert len(
        [
            event
            for event in store.events()
            if event["aggregate_id"] == payload["id"]
        ]
    ) == 1


def test_learning_requires_one_finalized_package_run_result(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="IMPLEMENTING")
    before = len(store.events())

    with pytest.raises(Exception) as rejected:
        management.commit_learning_operation(
            paths,
            "pkg",
            "insert",
            {
                "id": "unsupported",
                "title": "Unsupported observation",
                "evidence": [{"run_id": "missing-run"}],
            },
            actor=ACTOR,
        )

    assert getattr(rejected.value, "rule", "") == "learning-evidence-unverified"
    assert len(store.events()) == before


@pytest.mark.parametrize(
    "target",
    sorted(management.CANONICAL_AGGREGATE_TARGETS),
)
def test_package_mutation_cannot_write_a_canonical_read_projection(
    tmp_path,
    target,
):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="IMPLEMENTING")
    before = len(store.events())

    with pytest.raises(Exception) as rejected:
        management.apply_package_operation(
            paths,
            "pkg",
            operation="insert",
            target=target,
            payload={"id": "attempt"},
            actor=ACTOR,
        )

    assert getattr(rejected.value, "rule", "") == "canonical-aggregate-required"
    assert len(store.events()) == before


def test_experiment_status_projection_aggregates_all_runs(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="RESULT_ANALYSIS")
    state = store.state()
    state["aggregates"]["run"] = {
        "failed-run": {
            "id": "failed-run",
            "package_id": "pkg",
            "experiment_id": EXPERIMENT_ID,
            "status": "FAILED",
        },
        "passing-run": {
            "id": "passing-run",
            "package_id": "pkg",
            "experiment_id": EXPERIMENT_ID,
            "status": "COMPLETED",
            "latest_scientific_result": {
                "verdict": "PASS",
                "validity": "VALID",
                "result_sha256": "f" * 64,
                "evidence": [],
            },
        },
    }
    experiment = package_view_models(state)[0]["experiments"][0]
    assert experiment["status"] == "COMPLETED"

    state["aggregates"]["run"]["active-run"] = {
        "id": "active-run",
        "package_id": "pkg",
        "experiment_id": EXPERIMENT_ID,
        "status": "RUNNING",
    }
    experiment = package_view_models(state)[0]["experiments"][0]
    assert experiment["status"] == "RUNNING"


def test_terminal_run_result_is_the_only_fact_source(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="READY_TO_LAUNCH")
    store.commit(
        event_type="DecisionRecorded",
        aggregate_type="decision",
        aggregate_id="launch-ack",
        payload={
            "record": {
                "id": "launch-ack",
                "kind": "LAUNCH_ACK",
                "status": "ACKNOWLEDGED",
                "package_id": "pkg",
                "experiment_id": EXPERIMENT_ID,
                "actor": USER,
                "evidence": [{"kind": "ACTOR_ATTESTATION"}],
            }
        },
        actor=USER,
        idempotency_key="launch-ack",
        expected_version=0,
    )
    launch_run(
        paths=paths,
        package_id="pkg",
        experiment_id=EXPERIMENT_ID,
        run_id="run-smoke",
        command=[
            sys.executable,
            "-c",
            'print(\'{"step":1,"total":1,"loss":0.25}\')',
        ],
        cwd=tmp_path,
        use_tmux=False,
    )
    management.apply_package_operation(
        paths,
        "pkg",
        operation="update",
        target="status",
        payload={"to": "EXPERIMENT_RUNNING"},
        actor=ACTOR,
    )

    events = management.propagate_run_result(
        paths,
        "pkg",
        "run-smoke",
        actor=ACTOR,
    )
    assert [event["event_type"] for event in events] == ["RunResultFinalized"]
    state = store.state()
    package = state["aggregates"]["package"]["pkg"]
    assert "resultGateRows" not in package
    assert "methodsTried" not in package
    assert "resultBlocks" not in package
    projected = package_view_models(state)[0]
    assert projected["resultGateRows"][0]["run_id"] == "run-smoke"
    assert projected["methodsTried"][0]["run_id"] == "run-smoke"
    assert projected["resultBlocks"][0]["id"] == "P0::run-smoke"
    assert projected["liveChecks"][0]["run_id"] == "run-smoke"
    assert projected["openRuns"] == "none"
    experiment = state["aggregates"]["experiment"][EXPERIMENT_ID]
    assert experiment["id"] == EXPERIMENT_ID
    assert experiment["local_id"] == "P0"
    assert experiment["status"] == "READY"
    assert "latest_result_run_id" not in experiment


def test_rule_facade_commits_rule_aggregate_and_rebuilds_projection(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="IMPLEMENTING")
    cli = SCRIPTS / "research_op.py"
    payload = {
        "level": "package",
        "kind": "binding",
        "slug": "same-eval-split",
        "title": "Use the same evaluation split",
        "text": "All comparisons use the declared held-out split.",
        "rationale": "Keep result comparisons valid.",
        "addedAt": "2026-07-20",
    }

    result = subprocess.run(
        [
            sys.executable,
            str(cli),
            "--workspace",
            str(tmp_path),
            "--pkg",
            "pkg",
            "--op",
            "insert",
            "--target",
            "rule",
            "--payload",
            json.dumps(payload),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    output = json.loads(result.stdout)
    assert output["events"][0]["event_type"] == "AggregateUpserted"
    assert output["interface_written"] is True
    rule = store.state()["aggregates"]["rule"]["pkg#same-eval-split"]
    assert rule["kind"] == "binding"
    assert rule["package_id"] == "pkg"
    assert (paths.interface / "packages/pkg/analysis.html").is_file()


def test_projection_failure_is_audited_without_blocking_management_commit(
    tmp_path,
    monkeypatch,
):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = _create(paths, phase="IMPLEMENTING")

    def fail_projection(_paths):
        raise RuntimeError("synthetic interface failure")

    monkeypatch.setattr("lib.interface.build_interface", fail_projection)
    event = management.commit_change_operation(
        paths,
        "pkg",
        "insert",
        {
            "change_id": "change-projection-failure",
            "status": "reviewed",
            "summary": "canonical state still commits",
            "owned_files": ["src/model.py"],
            "validating_experiments": ["P0"],
        },
        actor=ACTOR,
        idempotency_key="projection-failure-management",
    )

    assert event["_interface_projection"]["written"] is False
    assert "synthetic interface failure" in event["_interface_projection"]["error"]
    change = store.state()["aggregates"]["change"][
        "pkg::change::change-projection-failure"
    ]
    assert change["local_id"] == "change-projection-failure"
    audit = [
        json.loads(line)
        for line in paths.audit_actions.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("domain_event_id") == event["event_id"]
    ]
    assert [row["outcome"] for row in audit] == [
        "COMMAND_COMMITTED",
        "PROJECTION_FAILED",
    ]
