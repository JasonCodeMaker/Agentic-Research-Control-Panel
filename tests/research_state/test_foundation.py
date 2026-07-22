import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from lib.research_state import (
    CommandConflict,
    CommandRejected,
    EventStore,
    ProjectionFailed,
    ResearchPaths,
    StateQuery,
    UpgradeRequired,
)
from lib.research_state import policy
from lib.research_state.reducer import EventIntegrityError, fold
from lib.research_state.io import append_jsonl_fsync, read_jsonl
from lib.research_state.schema import (
    SchemaViolation,
    enum,
    transition_map,
    validate_event_shape,
)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import legacy_policy_fixture as legacy_policy  # noqa: E402


ACTOR = {"type": "agent", "id": "test"}


def _package_record(package_id="package"):
    return {
        "id": package_id,
        "direction_id": "direction/test",
        "sourceVersion": 1,
        "sourceChange": "test",
        "sourceExperiments": [],
        "lifecycle": "ACTIVE",
        "phase": "CONTEXT_LOADED",
        "blocker": None,
    }


def _experiment_record(experiment_id):
    return {
        "id": experiment_id,
        "direction_id": "direction/test",
        "package_id": None,
        "spec": {
            "purpose": "validate",
            "config_ref": "config.yaml",
            "gate": "metric >= 1",
            "control_mode": "SUPERVISED",
        },
        "status": "PLANNED",
        "scope_status": "ACTIVE",
        "scope_confirmation": "CONFIRMED",
        "scope_version": 1,
        "scope_source": "test",
        "confirmed_direction_version": 1,
    }


def _store(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    store = EventStore(paths)
    store.initialize()
    return paths, store


def _legacy_to_new(category, status):
    return policy.from_legacy(category, status, {"currentBlocker": "blocked"})


def test_paths_precedence_and_upgrade_gate(tmp_path):
    env = {"RESEARCH_ROOT": "custom"}
    paths = ResearchPaths.resolve(workspace=tmp_path, environ=env)
    assert paths.root == tmp_path / "custom"

    legacy_workspace = tmp_path / "legacy"
    (legacy_workspace / "research_html").mkdir(parents=True)
    legacy_paths = ResearchPaths.resolve(workspace=legacy_workspace, environ={})
    with pytest.raises(UpgradeRequired, match="upgrade-required"):
        legacy_paths.initialize()


def test_runtime_identity_follows_shared_research_root(tmp_path):
    shared = tmp_path / "shared-state"
    left = ResearchPaths.resolve(
        workspace=tmp_path / "left",
        research_root=shared,
        environ={},
    )
    right = ResearchPaths.resolve(
        workspace=tmp_path / "right",
        research_root=shared,
        environ={},
    )

    assert left.root == right.root
    assert left.runtime == right.runtime


def test_concurrent_first_initialization_is_safe(tmp_path):
    script = (
        "from lib.research_state import EventStore, ResearchPaths;"
        f"p=ResearchPaths.resolve(workspace={str(tmp_path)!r});"
        "EventStore(p).initialize()"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(6)
    ]
    results = [process.communicate(timeout=10) for process in processes]
    assert [process.returncode for process in processes] == [0] * len(processes), results
    paths = ResearchPaths.resolve(workspace=tmp_path)
    assert paths.version_file.read_text(encoding="utf-8") == "1\n"
    assert EventStore(paths).state()["source_seq"] == 0


def test_first_jsonl_append_fsyncs_file_and_parent_directory(
    tmp_path,
    monkeypatch,
):
    observed: list[str] = []
    real_fsync = os.fsync

    def observed_fsync(descriptor):
        mode = os.fstat(descriptor).st_mode
        observed.append("directory" if stat.S_ISDIR(mode) else "file")
        return real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", observed_fsync)
    append_jsonl_fsync(tmp_path / "new" / "events.jsonl", {"seq": 1})

    assert observed == ["file", "directory"]


def test_policy_is_exactly_legacy_matrix_compatible():
    targets = [None, *sorted(legacy_policy.TARGETS)]
    for category, statuses in legacy_policy.STATES.items():
        for status in statuses:
            state = _legacy_to_new(category, status)
            for operation in ("check", "insert", "update", "delete"):
                for target in targets:
                    assert policy.is_legal(
                        state["lifecycle"],
                        state["phase"],
                        state["blocker"],
                        operation,
                        target,
                    ) == legacy_policy.is_legal(
                        category,
                        status,
                        operation,
                        target,
                    )


def test_commit_is_idempotent_and_replay_is_stable(tmp_path):
    paths, store = _store(tmp_path)
    kwargs = {
        "event_type": "AggregateUpserted",
        "aggregate_type": "package",
        "aggregate_id": "pkg-1",
        "payload": {
            "record": {
                "id": "pkg-1",
                "lifecycle": "ACTIVE",
                "phase": "CONTEXT_LOADED",
                "blocker": None,
                "direction_id": "direction/test",
                "sourceVersion": 1,
                "sourceChange": "test",
                "sourceExperiments": [],
            }
        },
        "actor": ACTOR,
        "idempotency_key": "same-command",
        "expected_version": 0,
    }
    first = store.commit(**kwargs)
    second = store.commit(**kwargs)
    assert second["event_id"] == first["event_id"]
    assert len(store.events()) == 1
    assert store.state() == fold(store.events())
    assert StateQuery(paths).show("package", "pkg-1")["source_hash"] == first["hash"]


def test_idempotent_projection_audit_uses_the_current_version(tmp_path):
    paths, store = _store(tmp_path)
    create = {
        "event_type": "AggregateUpserted",
        "aggregate_type": "package",
        "aggregate_id": "pkg-1",
        "payload": {"record": _package_record("pkg-1")},
        "actor": ACTOR,
        "idempotency_key": "create-for-projection-replay",
        "expected_version": 0,
    }
    first = store.commit(**create)
    store.commit(
        event_type="AggregatePatched",
        aggregate_type="package",
        aggregate_id="pkg-1",
        payload={"patch": {"lastAction": "advanced"}},
        actor=ACTOR,
        idempotency_key="advance-after-create",
        expected_version=1,
    )

    replay = store.commit(**create, render=lambda: [])

    assert replay["event_id"] == first["event_id"]
    rows = [
        row
        for row in read_jsonl(paths.audit_actions)
        if row["outcome"] == "PROJECTION_RENDERED"
    ]
    assert rows[-1]["state_before_version"] == 2
    assert rows[-1]["state_after_version"] == 2
    assert rows[-1]["domain_event_id"] == first["event_id"]


def test_initialize_rebuilds_missing_projection_from_events(tmp_path):
    paths, store = _store(tmp_path)
    event = store.commit(
        event_type="AggregateUpserted",
        aggregate_type="package",
        aggregate_id="pkg-1",
        payload={"record": _package_record("pkg-1")},
        actor=ACTOR,
        idempotency_key="projection-rebuild-package",
        expected_version=0,
    )

    paths.current.unlink()
    EventStore(paths).initialize()

    rebuilt = EventStore(paths).state()
    assert rebuilt == fold([event])
    assert rebuilt["source_seq"] == 1
    assert rebuilt["source_hash"] == event["hash"]


def test_stale_expected_version_rejects_without_state_change(tmp_path):
    _, store = _store(tmp_path)
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="package",
        aggregate_id="package",
        payload={"record": _package_record()},
        actor=ACTOR,
        idempotency_key="create-package",
        expected_version=0,
    )
    with pytest.raises(CommandConflict, match="current version is 1"):
        store.commit(
            event_type="AggregatePatched",
            aggregate_type="package",
            aggregate_id="package",
            payload={"patch": {"goal": "new"}},
            actor=ACTOR,
            idempotency_key="stale-package",
            expected_version=0,
        )
    assert len(store.events()) == 1


def test_schema_rejection_is_audited_before_state_write(tmp_path):
    paths, store = _store(tmp_path)
    with pytest.raises(CommandRejected, match="unknown event_type"):
        store.commit(
            event_type="InventedEvent",
            aggregate_type="project",
            aggregate_id="project",
            payload={"record": {}},
            actor=ACTOR,
            idempotency_key="bad-event",
            command_id="cmd-bad-event",
        )

    assert store.events() == []
    rows = [
        row
        for row in read_jsonl(paths.audit_actions)
        if row["command_id"] == "cmd-bad-event"
    ]
    assert [row["outcome"] for row in rows] == ["COMMAND_REJECTED"]
    assert rows[-1]["rejection_reason"]["rule"] == "event-type-unknown"


def test_rejection_reason_is_recursively_redacted(tmp_path):
    paths, store = _store(tmp_path)
    store.record_rejected_attempt(
        command_name="sensitive-rejection",
        actor=ACTOR,
        payload={},
        rule="synthetic",
        detail={
            "message": "safe diagnostic",
            "nested": {
                "apiKey": "api-secret",
                "access_token": "token-secret",
            },
        },
    )

    row = read_jsonl(paths.audit_actions)[-1]
    assert row["rejection_reason"] == {
        "rule": "synthetic",
        "detail": {
            "message": "safe diagnostic",
            "nested": {
                "apiKey": "[REDACTED]",
                "access_token": "[REDACTED]",
            },
        },
    }


@pytest.mark.parametrize(
    ("event_type", "aggregate_type", "payload"),
    [
        (
            "AggregateUpserted",
            "project",
            {"record": {"id": "project"}},
        ),
        (
            "AggregatePatched",
            "direction",
            {"patch": {"status": "ACTIVE"}},
        ),
        (
            "AggregateRemoved",
            "experiment",
            {},
        ),
    ],
)
def test_generic_events_cannot_bypass_scope_governance(
    tmp_path,
    event_type,
    aggregate_type,
    payload,
):
    _, store = _store(tmp_path)
    with pytest.raises(CommandRejected) as rejected:
        store.commit(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=f"{aggregate_type}/bypass",
            payload=payload,
            actor=ACTOR,
            idempotency_key=f"scope-bypass:{event_type}",
        )

    assert rejected.value.rule == "scope-semantic-event-required"
    assert store.events() == []


@pytest.mark.parametrize(
    "bindings",
    [
        [
            {
                "aggregate_id": "experiment/one",
                "expected_version": 1,
                "aggregate_version": 2,
                "patch": {
                    "local_id": "P0",
                    "package_id": "pkg",
                    "status": "READY",
                    "spec": {
                        "purpose": "bypass",
                        "config_ref": "evil.yaml",
                        "gate": "always",
                        "control_mode": "AUTONOMOUS",
                    },
                },
            }
        ],
        [
            {
                "aggregate_id": "experiment/one",
                "expected_version": 1,
                "aggregate_version": 2,
                "patch": {
                    "local_id": "P0",
                    "package_id": "other",
                    "status": "READY",
                },
            }
        ],
        [
            {
                "aggregate_id": experiment_id,
                "expected_version": 1,
                "aggregate_version": 2,
                "patch": {
                    "local_id": "P0",
                    "package_id": "pkg",
                    "status": "READY",
                },
            }
            for experiment_id in ("experiment/one", "experiment/two")
        ],
    ],
)
def test_atomic_package_event_cannot_bypass_experiment_contract(
    tmp_path,
    bindings,
):
    paths, _ = _store(tmp_path)
    fixture_store = EventStore(paths, fixture_mode=True)
    for experiment_id in ("experiment/one", "experiment/two"):
        fixture_store.commit(
            event_type="AggregateImported",
            aggregate_type="experiment",
            aggregate_id=experiment_id,
            payload={
                "record": _experiment_record(experiment_id),
                "_migration": {
                    "source": "fixture",
                    "identity": experiment_id,
                    "sha256": "a" * 64,
                },
            },
            actor=ACTOR,
            idempotency_key=f"fixture:{experiment_id}",
        )
    package = _package_record("pkg")
    package["sourceExperiments"] = [
        {"id": binding["aggregate_id"], "version": 1, "source": "test"}
        for binding in bindings
    ]

    with pytest.raises(CommandRejected):
        EventStore(paths).commit(
            event_type="PackageMaterialized",
            aggregate_type="package",
            aggregate_id="pkg",
            payload={"record": package, "experiment_bindings": bindings},
            actor=ACTOR,
            idempotency_key="package-bypass",
            expected_version=0,
        )

    assert "pkg" not in EventStore(paths).state()["aggregates"]["package"]


def test_status_event_cannot_reconfirm_scope_without_proposal(tmp_path):
    paths, _ = _store(tmp_path)
    EventStore(paths, fixture_mode=True).commit(
        event_type="AggregateImported",
        aggregate_type="experiment",
        aggregate_id="experiment/one",
        payload={
            "record": {
                **_experiment_record("experiment/one"),
                "status": "BLOCKED",
                "scope_confirmation": "STALE",
            },
            "_migration": {
                "source": "fixture",
                "identity": "experiment/one",
                "sha256": "b" * 64,
            },
        },
        actor=ACTOR,
        idempotency_key="fixture:stale-experiment",
    )

    with pytest.raises(CommandRejected) as rejected:
        EventStore(paths).commit(
            event_type="ExperimentStatusChanged",
            aggregate_type="experiment",
            aggregate_id="experiment/one",
            payload={
                "patch": {
                    "scope_confirmation": "CONFIRMED",
                    "confirmed_direction_version": 2,
                    "scope_status": "ACTIVE",
                    "status": "READY",
                }
            },
            actor=ACTOR,
            idempotency_key="reconfirm-bypass",
            expected_version=1,
        )

    assert rejected.value.rule == "scope-effect-causation-required"


def test_scope_semantic_event_requires_accepted_proposal_causation(tmp_path):
    _, store = _store(tmp_path)
    with pytest.raises(CommandRejected) as rejected:
        store.commit(
            event_type="ScopeCommitted",
            aggregate_type="project",
            aggregate_id="project/bypass",
            payload={"record": {"id": "project/bypass"}},
            actor=ACTOR,
            idempotency_key="scope-without-proposal",
        )

    assert rejected.value.rule == "proposal-causation-required"
    assert store.events() == []


def test_scope_semantic_event_cannot_depart_from_accepted_snapshot(tmp_path):
    _, store = _store(tmp_path)
    node = {
        "id": "project/bound",
        "level": "project",
        "parents": [],
        "version": 1,
        "status": "ACTIVE",
        "spec": {"objective": "accepted"},
        "source": "test",
    }
    proposal = {
        "id": "proposal/bound",
        "level": "project",
        "node_id": node["id"],
        "op": "create",
        "gate": "USER_ONLY",
        "proposed_spec": node["spec"],
        "proposed_node": node,
        "invalidates": [],
        "reopens": [],
        "dial_revert": [],
    }
    store.commit(
        event_type="ProposalSubmitted",
        aggregate_type="proposal",
        aggregate_id=proposal["id"],
        payload={
            "record": {
                **proposal,
                "proposal_hash": "accepted-hash",
            }
        },
        actor=ACTOR,
        idempotency_key="proposal-submit-bound",
    )
    accepted = store.commit(
        event_type="ProposalAccepted",
        aggregate_type="proposal",
        aggregate_id=proposal["id"],
        payload={
            "record": {
                "id": proposal["id"],
                "proposal_hash": "accepted-hash",
                "accepted_proposal": proposal,
            }
        },
        actor={"type": "user", "id": "pm"},
        idempotency_key="proposal-accept-bound",
        expected_version=1,
    )

    with pytest.raises(CommandRejected) as rejected:
        store.commit(
            event_type="ScopeCommitted",
            aggregate_type="project",
            aggregate_id=node["id"],
            payload={
                "record": {
                    **node,
                    "spec": {"objective": "tampered"},
                },
                "proposal_binding": {
                    "proposal_id": proposal["id"],
                    "proposal_hash": "accepted-hash",
                    "proposed_node": node,
                    "op": "create",
                    "gate": "USER_ONLY",
                    "invalidates": [],
                    "reopens": [],
                    "dial_revert": [],
                },
            },
            actor=ACTOR,
            idempotency_key="scope-tampered-after-accept",
            causation_id=accepted["event_id"],
        )

    assert rejected.value.rule == "scope-record-proposal-mismatch"
    assert store.state()["aggregates"]["project"] == {}


def test_projection_failure_never_rolls_back_committed_state(tmp_path):
    paths, store = _store(tmp_path)

    def broken_renderer():
        raise RuntimeError("renderer unavailable")

    with pytest.raises(ProjectionFailed, match="state committed") as raised:
        store.commit(
            event_type="AggregateUpserted",
            aggregate_type="package",
            aggregate_id="package",
            payload={"record": _package_record()},
            actor=ACTOR,
            idempotency_key="projection-failure",
            command_id="cmd-projection-failure",
            render=broken_renderer,
        )

    assert raised.value.committed_event["event_type"] == "AggregateUpserted"
    assert (
        store.state()["aggregates"]["package"]["package"]["phase"]
        == "CONTEXT_LOADED"
    )
    rows = [
        row
        for row in read_jsonl(paths.audit_actions)
        if row["command_id"] == "cmd-projection-failure"
    ]
    assert [row["outcome"] for row in rows] == [
        "COMMAND_COMMITTED",
        "PROJECTION_FAILED",
    ]


def test_hash_chain_tamper_is_detected(tmp_path):
    paths, store = _store(tmp_path)
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="package",
        aggregate_id="package",
        payload={"record": _package_record()},
        actor=ACTOR,
        idempotency_key="create-package",
    )
    row = json.loads(paths.events.read_text(encoding="utf-8"))
    row["payload"]["record"]["goal"] = "tampered"
    paths.events.write_text(json.dumps(row) + "\n", encoding="utf-8")
    # JSONL is a compatibility export, so ordinary state reads stay on the
    # SQLite fast path. An audit-strength snapshot still verifies the complete
    # exported hash chain and fails closed on tampering.
    assert "goal" not in store.state()["aggregates"]["package"]["package"]
    with pytest.raises(EventIntegrityError, match="hash mismatch"):
        store.snapshot()


def test_unknown_event_schema_version_fails_closed():
    event = {
        "seq": 1,
        "event_id": "evt",
        "schema_version": 999,
        "event_type": "AggregateUpserted",
        "aggregate_type": "project",
        "aggregate_id": "project",
        "aggregate_version": 1,
        "command_id": "cmd",
        "idempotency_key": "key",
        "actor": ACTOR,
        "occurred_at": "2026-01-01T00:00:00+00:00",
        "payload": {"record": {}},
        "prev_hash": "",
        "hash": "",
    }
    with pytest.raises(SchemaViolation, match="unknown event schema_version"):
        validate_event_shape(event)


def test_semantic_event_cannot_target_the_wrong_aggregate(tmp_path):
    _, store = _store(tmp_path)
    with pytest.raises(CommandRejected, match="requires aggregate_type='decision'"):
        store.commit(
            event_type="DecisionRecorded",
            aggregate_type="package",
            aggregate_id="pkg",
            payload={"record": {"id": "pkg"}},
            actor=ACTOR,
            idempotency_key="wrong-semantic-target",
        )
    assert store.events() == []


@pytest.mark.parametrize(
    ("aggregate_type", "event_type", "record", "message"),
    [
        (
            "decision",
            "DecisionRecorded",
            {
                "id": "decision/missing-evidence",
                "actor": ACTOR,
            },
            "decision aggregate missing required field",
        ),
        (
            "decision",
            "DecisionRecorded",
            {
                "id": "decision/missing-actor",
                "evidence": [{"kind": "REFERENCE", "uri": "note://review"}],
            },
            "decision aggregate missing required field",
        ),
        (
            "learning",
            "LearningRecorded",
            {"id": "learning/missing-evidence"},
            "learning aggregate missing required field",
        ),
        (
            "change",
            "AggregateUpserted",
            {
                "id": "change/incomplete",
                "package_id": "pkg",
                "owned_files": ["src/model.py"],
            },
            "change aggregate missing required field",
        ),
    ],
)
def test_semantic_aggregate_contracts_reject_incomplete_records(
    tmp_path,
    aggregate_type,
    event_type,
    record,
    message,
):
    _, store = _store(tmp_path)
    with pytest.raises(CommandRejected, match=message):
        store.commit(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=record["id"],
            payload={"record": record},
            actor=ACTOR,
            idempotency_key=f"incomplete:{record['id']}",
        )
    assert store.events() == []


def test_decision_identity_is_immutable_but_exact_retry_is_idempotent(tmp_path):
    _, store = _store(tmp_path)
    record = {
        "id": "decision/route-a",
        "actor": ACTOR,
        "route": "RUN_NEXT_EXPERIMENT",
        "evidence": [{"kind": "REFERENCE", "uri": "note://review"}],
    }
    first = store.commit(
        event_type="DecisionRecorded",
        aggregate_type="decision",
        aggregate_id=record["id"],
        payload={"record": record},
        actor=ACTOR,
        idempotency_key="decision:route-a",
        expected_version=0,
    )
    retried = store.commit(
        event_type="DecisionRecorded",
        aggregate_type="decision",
        aggregate_id=record["id"],
        payload={"record": record},
        actor=ACTOR,
        idempotency_key="decision:route-a",
        expected_version=0,
    )
    assert retried["event_id"] == first["event_id"]
    assert len(store.events()) == 1

    with pytest.raises(CommandRejected, match="Decision identities are immutable"):
        store.commit(
            event_type="DecisionRecorded",
            aggregate_type="decision",
            aggregate_id=record["id"],
            payload={
                "record": {
                    **record,
                    "route": "TERMINATE",
                }
            },
            actor=ACTOR,
            idempotency_key="decision:route-a:replacement",
            expected_version=1,
        )
    assert len(store.events()) == 1


def test_brainstorm_and_package_mutations_fold_semantically(tmp_path):
    _, store = _store(tmp_path)
    store.commit(
        event_type="BrainstormCreated",
        aggregate_type="brainstorm",
        aggregate_id="idea-1",
        payload={"record": {"title": "Idea"}},
        actor=ACTOR,
        idempotency_key="idea-create",
    )
    store.commit(
        event_type="BrainstormArchived",
        aggregate_type="brainstorm",
        aggregate_id="idea-1",
        payload={"patch": {"archive_reason": "converted"}},
        actor=ACTOR,
        idempotency_key="idea-archive",
        expected_version=1,
    )
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="package",
        aggregate_id="pkg",
        payload={
            "record": {
                "id": "pkg",
                "direction_id": "direction/test",
                "sourceVersion": 1,
                "sourceChange": "test",
                "sourceExperiments": [],
                "lifecycle": "ACTIVE",
                "phase": "IMPLEMENTING",
                "blocker": None,
                "rows": [{"id": "r1", "value": 1}],
            }
        },
        actor=ACTOR,
        idempotency_key="package-create",
    )
    store.commit(
        event_type="PackageMutationApplied",
        aggregate_type="package",
        aggregate_id="pkg",
        payload={
            "operations": [
                {
                    "operation": "upsert_by_id",
                    "target": "rows",
                    "value": {"id": "r1", "value": 2},
                },
                {
                    "operation": "append",
                    "target": "rows",
                    "value": {"id": "r2", "value": 3},
                },
            ]
        },
        actor=ACTOR,
        idempotency_key="package-mutate",
        expected_version=1,
    )

    state = store.state()["aggregates"]
    assert state["brainstorm"]["idea-1"]["status"] == "ARCHIVED"
    assert state["package"]["pkg"]["rows"] == [
        {"id": "r1", "value": 2},
        {"id": "r2", "value": 3},
    ]


def test_central_schema_owns_package_phase_graph():
    phases = set(enum("package_phase"))
    graph = transition_map("package_phase")

    assert set(graph) == phases
    assert set(target for targets in graph.values() for target in targets) <= phases
    assert "BLOCKED" not in phases
    assert "STOPPED" not in phases


def test_note_is_content_addressed_and_not_duplicated(tmp_path):
    paths, store = _store(tmp_path)
    first = store.write_note("# Same note\n")
    second = store.write_note("# Same note\n")
    assert first == second
    assert (paths.root / first["uri"]).read_text(encoding="utf-8") == "# Same note\n"
    assert len(list(paths.notes.iterdir())) == 1


def test_run_terminal_requires_launched_event(tmp_path):
    _, store = _store(tmp_path)
    store.commit(
        event_type="RunLaunchAuthorized",
        aggregate_type="run",
        aggregate_id="run-1",
        payload={
            "record": {
                "id": "run-1",
                "package_id": "pkg",
                "experiment_id": "exp",
            }
        },
        actor=ACTOR,
        idempotency_key="authorize",
    )
    with pytest.raises(CommandRejected, match="earlier RunLaunched"):
        store.commit(
            event_type="RunTerminal",
            aggregate_type="run",
            aggregate_id="run-1",
            payload={"status": "COMPLETED"},
            actor=ACTOR,
            idempotency_key="terminal",
            expected_version=1,
        )
    assert len(store.events()) == 1


def test_only_research_root_environment_selects_the_store(tmp_path):
    legacy = tmp_path / "ignored-legacy-root"
    paths = ResearchPaths.resolve(
        workspace=tmp_path,
        environ={
            "RESEARCH_RUNTIME_ROOT": str(legacy),
            "RESEARCH_ROOT": str(tmp_path / "canonical-root"),
        },
    )
    assert paths.root == tmp_path / "canonical-root"

    with pytest.warns(DeprecationWarning, match="RESEARCH_RUNTIME_ROOT"):
        defaulted = ResearchPaths.resolve(
            workspace=tmp_path,
            environ={"RESEARCH_RUNTIME_ROOT": str(legacy)},
        )
    assert defaulted.root == legacy


def test_querying_an_uninitialized_store_fails_closed(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    with pytest.raises(UpgradeRequired, match="not initialized"):
        EventStore(paths).state()
