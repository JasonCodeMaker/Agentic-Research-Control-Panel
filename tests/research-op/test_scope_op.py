"""CLI integration for event-backed Scope and hash-bound Proposal commits."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "skills" / "research-op" / "scripts" / "research_op.py"
TRIAGE = ROOT / "skills" / "research-scope" / "scripts" / "triage.py"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills/research-op/scripts"))

from lib.research_state import (  # noqa: E402
    CommandRejected,
    EventStore,
    ResearchPaths,
    StateQuery,
)
from lib.research_state.reducer import EventIntegrityError  # noqa: E402
import management  # noqa: E402
from tests.scope_fixtures import (  # noqa: E402
    direction_node,
    direction_spec,
    experiment_node,
    project_node,
    project_spec,
)


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _triage(args, cwd):
    return subprocess.run(
        [sys.executable, str(TRIAGE), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _paths(workspace):
    paths = ResearchPaths.resolve(workspace=workspace, research_root=".research")
    EventStore(paths).initialize()
    return paths


def _direction_payload(gate):
    return {
        "id": "dir/test-pkg",
        "level": "direction",
        "parents": ["project/composed-video-retrieval"],
        "version": 1,
        "status": "ACTIVE",
        "spec": direction_spec(metric={"name": "nDCG@10", "dir": "higher"}),
        "source": "txn-0",
        "op": "create",
        "gate": gate,
        "trigger": "exp#42",
        "cause": "metric saturated",
    }


def _project_payload():
    return {
        "id": "project/composed-video-retrieval",
        "level": "project",
        "parents": [],
        "version": 1,
        "status": "ACTIVE",
        "spec": project_spec(goal="Investigating Composed Video Retrieval"),
        "source": "triage:project-composed-video-retrieval",
        "op": "create",
        "gate": "USER_ONLY",
        "trigger": "PM_ACCEPT",
        "cause": "User accepted the clear Project Scope Review.",
    }


def _scope_command(item_id):
    return [
        "--pkg",
        "_scope",
        "--op",
        "scope-transition",
        "--from-triage",
        item_id,
        "--research-root",
        ".research",
    ]


def _proposal_item(payload=None, *, item_id=None):
    payload = payload or _project_payload()
    return {
        "id": item_id or (
            "project-covr"
            if payload["id"] == "project/composed-video-retrieval"
            else (
                f"proposal-{payload['level']}-{payload['id'].replace('/', '-')}-"
                f"v{payload['version']}"
            )
        ),
        "level": payload["level"],
        "node_id": payload["id"],
        "op": payload["op"],
        "gate": payload["gate"],
        "change": f"{payload['op']} {payload['id']}.",
        "rationale": "The PM accepted the clear Project Scope Review.",
        "proposed_spec": payload["spec"],
        "proposed_node": {
            key: payload[key]
            for key in (
                "id",
                "level",
                "parents",
                "version",
                "status",
                "spec",
                "source",
            )
        },
        "invalidates": list(payload.get("invalidates") or []),
        "reopens": list(payload.get("reopens") or []),
        "dial_revert": list(payload.get("dial_revert") or []),
    }


def _accept_proposal(workspace, payload=None, *, item_id=None):
    item = _proposal_item(payload, item_id=item_id)
    proposed = _triage(
        [
            "--research-root",
            ".research",
            "propose",
            "--item",
            json.dumps(item),
        ],
        cwd=workspace,
    )
    assert proposed.returncode == 0, proposed.stdout + proposed.stderr
    pending = _triage(
        [
            "--research-root",
            ".research",
            "pending",
        ],
        cwd=workspace,
    )
    visible_hash = json.loads(pending.stdout)[0]["proposal_hash"]
    disposed = _triage(
        [
            "--research-root",
            ".research",
            "dispose",
            "--id",
            item["id"],
            "--decision",
            "ACCEPTED",
            "--proposal-hash",
            visible_hash,
            "--actor-type",
            "user",
            "--actor-id",
            "test-pm",
        ],
        cwd=workspace,
    )
    assert disposed.returncode == 0, disposed.stdout + disposed.stderr
    return item["id"]


def _commit_payload(workspace, payload, *extra):
    item_id = _accept_proposal(workspace, payload)
    return _run([*_scope_command(item_id), *extra], cwd=workspace)


def _seed_project(workspace):
    return _commit_payload(workspace, _project_payload())


def test_scope_transition_legal_commits_event_and_global_audit(tmp_path):
    paths = _paths(tmp_path)
    assert _seed_project(tmp_path).returncode == 0
    result = _commit_payload(
        tmp_path,
        _direction_payload("USER_CROSS_MODEL_AUDIT"),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["aggregate"] == "direction/dir/test-pkg"
    direction = EventStore(paths).state()["aggregates"]["direction"]["dir/test-pkg"]
    assert direction["spec"]["metric"]["name"] == "nDCG@10"
    assert not (tmp_path / "outputs" / "_scope" / "transitions.jsonl").exists()
    assert '"validation":"PASSED"' in paths.audit_actions.read_text(encoding="utf-8")


def test_scope_transition_illegal_gate_is_audited_before_write(tmp_path):
    paths = _paths(tmp_path)
    item = _proposal_item(_direction_payload("AGENT_DEFERRED_ACK"))
    result = _triage(
        [
            "--research-root",
            ".research",
            "propose",
            "--item",
            json.dumps(item),
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 2
    envelope = json.loads(result.stdout)
    assert envelope["rejected"] is True
    assert envelope["rule"] == "scope-gate"
    assert EventStore(paths).state()["aggregates"]["direction"] == {}
    audit = paths.audit_actions.read_text(encoding="utf-8")
    assert "scope-gate" in audit and '"validation":"OP_REJECTED"' in audit


def test_project_scope_needs_no_package_or_interface(tmp_path):
    paths = _paths(tmp_path)
    result = _commit_payload(tmp_path, _project_payload())

    assert result.returncode == 0, result.stdout + result.stderr
    project = EventStore(paths).state()["aggregates"]["project"][
        "project/composed-video-retrieval"
    ]
    assert project["spec"]["goal"] == "Investigating Composed Video Retrieval"
    assert not (tmp_path / "research_html").exists()
    assert not (tmp_path / "outputs").exists()


def test_experiment_scope_is_stored_without_inferred_dependencies(tmp_path):
    paths = _paths(tmp_path)
    assert _commit_payload(
        tmp_path,
        {
            **project_node(),
            "op": "create",
            "gate": "USER_ONLY",
        },
    ).returncode == 0
    assert _commit_payload(
        tmp_path,
        {
            **direction_node(),
            "op": "create",
            "gate": "USER_CROSS_MODEL_AUDIT",
        },
    ).returncode == 0
    node = experiment_node()
    payload = {
        **node,
        "op": "create",
        "gate": "AGENT_DEFERRED_ACK",
    }
    result = _commit_payload(tmp_path, payload)

    assert result.returncode == 0, result.stdout + result.stderr
    experiment = EventStore(paths).state()["aggregates"]["experiment"][node["id"]]
    assert experiment["direction_id"] == node["parents"][0]
    assert experiment["spec"] == node["spec"]
    assert "aliases" not in experiment
    assert "after" not in experiment
    assert "after" not in experiment["spec"]


def test_scope_revision_rejects_stale_expected_version(tmp_path):
    paths = _paths(tmp_path)
    assert _seed_project(tmp_path).returncode == 0
    first = _direction_payload("USER_CROSS_MODEL_AUDIT")
    assert _commit_payload(tmp_path, first).returncode == 0
    revised = {
        **first,
        "version": 2,
        "op": "revise",
        "cause": "tighten the accepted success gate",
    }
    item_id = _accept_proposal(tmp_path, revised)
    result = _run(
        [*_scope_command(item_id), "--expected-version", "0"],
        cwd=tmp_path,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["rule"] == "expected-version-conflict"
    assert len(EventStore(paths).state()["aggregates"]["direction"]) == 1
    assert "expected-version-conflict" in paths.audit_actions.read_text(
        encoding="utf-8"
    )


def test_scope_spec_version_is_independent_from_aggregate_version(tmp_path):
    paths = _paths(tmp_path)
    assert _seed_project(tmp_path).returncode == 0
    first = _direction_payload("USER_CROSS_MODEL_AUDIT")
    assert _commit_payload(tmp_path, first).returncode == 0
    store = EventStore(paths, fixture_mode=True)
    store.commit(
        event_type="AggregatePatched",
        aggregate_type="direction",
        aggregate_id=first["id"],
        payload={"patch": {"operational_note": "non-Scope state"}},
        actor={"type": "system", "id": "test"},
        idempotency_key="direction-operational-note",
        expected_version=1,
    )
    revised = {
        **first,
        "version": 2,
        "op": "revise",
        "cause": "tighten the accepted success gate",
    }

    result = _commit_payload(tmp_path, revised)

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["aggregate_version"] == 3
    assert EventStore(paths).state()["aggregates"]["direction"][first["id"]][
        "version"
    ] == 2


def test_scope_transition_from_accepted_proposal_binds_causation(tmp_path):
    paths = _paths(tmp_path)
    item_id = _accept_proposal(tmp_path)
    result = _run(
        [
            "--pkg",
            "_scope",
            "--op",
            "scope-transition",
            "--from-triage",
            item_id,
            "--research-root",
            ".research",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    events = EventStore(paths).events()
    accepted = next(event for event in events if event["event_type"] == "ProposalAccepted")
    scope_event = events[-1]
    assert scope_event["causation_id"] == accepted["event_id"]
    assert scope_event["payload"]["record"]["_scope_transition"]["trigger"] == (
        "triage:project-covr"
    )


def test_scope_transition_from_proposal_is_idempotent(tmp_path):
    paths = _paths(tmp_path)
    item_id = _accept_proposal(tmp_path)
    args = [
        "--pkg",
        "_scope",
        "--op",
        "scope-transition",
        "--from-triage",
        item_id,
        "--research-root",
        ".research",
    ]
    first = _run(args, cwd=tmp_path)
    second = _run(args, cwd=tmp_path)

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    assert json.loads(first.stdout)["idempotent"] is False
    assert json.loads(second.stdout)["idempotent"] is True
    assert len(EventStore(paths).events()) == 3


def test_scope_accept_combines_user_disposition_and_bound_commit(tmp_path):
    paths = _paths(tmp_path)
    item = _proposal_item()
    proposed = _triage(
        [
            "--research-root",
            ".research",
            "propose",
            "--item",
            json.dumps(item),
            "--receipt",
        ],
        cwd=tmp_path,
    )
    assert proposed.returncode == 0, proposed.stdout + proposed.stderr
    receipt = json.loads(proposed.stdout)
    args = [
        "--pkg",
        "_scope",
        "--op",
        "scope-accept",
        "--from-triage",
        receipt["id"],
        "--proposal-hash",
        receipt["proposal_hash"],
        "--actor-type",
        "user",
        "--actor-id",
        "test-pm",
        "--research-root",
        ".research",
    ]

    first = _run(args, cwd=tmp_path)
    second = _run(args, cwd=tmp_path)

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    first_receipt = json.loads(first.stdout)
    second_receipt = json.loads(second.stdout)
    assert first_receipt["op"] == "scope-accept"
    assert first_receipt["scope_id"] == "project/composed-video-retrieval"
    assert first_receipt["idempotent"] is False
    assert "record" not in first_receipt
    assert second_receipt["idempotent"] is True
    assert EventStore(paths).state()["aggregates"]["project"][
        "project/composed-video-retrieval"
    ]["status"] == "ACTIVE"
    assert [event["event_type"] for event in EventStore(paths).events()] == [
        "ProposalSubmitted",
        "ProposalAccepted",
        "ScopeCommitted",
    ]


def test_scope_accept_requires_explicit_user_actor(tmp_path):
    paths = _paths(tmp_path)
    item = _proposal_item()
    proposed = _triage(
        [
            "--research-root",
            ".research",
            "propose",
            "--item",
            json.dumps(item),
            "--receipt",
        ],
        cwd=tmp_path,
    )
    receipt = json.loads(proposed.stdout)

    result = _run(
        [
            "--pkg",
            "_scope",
            "--op",
            "scope-accept",
            "--from-triage",
            receipt["id"],
            "--proposal-hash",
            receipt["proposal_hash"],
            "--research-root",
            ".research",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["rule"] == "proposal-disposition-user-required"
    assert EventStore(paths).state()["aggregates"]["project"] == {}
    assert [row["id"] for row in management.pending_proposals(paths)] == [
        item["id"]
    ]


def test_scope_accept_resumes_after_acceptance_precedes_failed_commit(tmp_path):
    paths = _paths(tmp_path)
    item = _proposal_item()
    proposed = _triage(
        [
            "--research-root",
            ".research",
            "propose",
            "--item",
            json.dumps(item),
            "--receipt",
        ],
        cwd=tmp_path,
    )
    receipt = json.loads(proposed.stdout)
    base = [
        "--pkg",
        "_scope",
        "--op",
        "scope-accept",
        "--from-triage",
        receipt["id"],
        "--proposal-hash",
        receipt["proposal_hash"],
        "--actor-type",
        "user",
        "--actor-id",
        "test-pm",
        "--research-root",
        ".research",
    ]

    failed = _run([*base, "--expected-version", "1"], cwd=tmp_path)
    resumed = _run(base, cwd=tmp_path)

    assert failed.returncode == 2
    assert json.loads(failed.stdout)["rule"] == "expected-version-conflict"
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert EventStore(paths).state()["aggregates"]["proposal"][item["id"]][
        "disposition"
    ] == "ACCEPTED"
    assert EventStore(paths).state()["aggregates"]["project"][
        "project/composed-video-retrieval"
    ]["status"] == "ACTIVE"


def test_scope_transition_ignores_tampered_compatibility_export(tmp_path):
    paths = _paths(tmp_path)
    item_id = _accept_proposal(tmp_path)
    rows = [
        json.loads(line)
        for line in paths.events.read_text(encoding="utf-8").splitlines()
    ]
    rows[-1]["payload"]["record"]["accepted_proposal"]["proposed_node"]["spec"][
        "goal"
    ] = "Tampered Project Objective"
    paths.events.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = _run(
        [
            "--pkg",
            "_scope",
            "--op",
            "scope-transition",
            "--from-triage",
            item_id,
            "--research-root",
            ".research",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0
    state = EventStore(paths).state()
    assert state["aggregates"]["project"][
        "project/composed-video-retrieval"
    ]["spec"]["goal"] != "Tampered Project Objective"

    # Ordinary commands use SQLite authority. Explicit audit reads still
    # detect a corrupted compatibility export, and recovery rebuilds it.
    with pytest.raises(EventIntegrityError, match="hash mismatch"):
        EventStore(paths).snapshot()
    EventStore(paths).recover()
    assert EventStore(paths).snapshot()[0] == EventStore(paths).state()


def test_direct_scope_commit_without_accepted_proposal_is_rejected_and_audited(
    tmp_path,
):
    paths = _paths(tmp_path)

    with pytest.raises(CommandRejected, match="ProposalAccepted"):
        management.commit_scope_transition(paths, _project_payload())

    assert EventStore(paths).events() == []
    audit = [
        json.loads(line)
        for line in paths.audit_actions.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["outcome"] for row in audit[-1:]] == ["COMMAND_REJECTED"]
    assert audit[-1]["rejection_reason"]["rule"] == "proposal-causation-required"


def test_malformed_proposal_is_rejected_before_governance_state(tmp_path):
    paths = _paths(tmp_path)
    malformed = {
        "id": "proposal-incomplete",
        "level": "direction",
        "node_id": "dir/missing",
    }

    with pytest.raises(CommandRejected, match="missing required fields"):
        management.submit_proposal(paths, malformed)

    assert EventStore(paths).state()["aggregates"]["proposal"] == {}
    audit = [
        json.loads(line)
        for line in paths.audit_actions.read_text(encoding="utf-8").splitlines()
    ]
    assert audit[-1]["outcome"] == "COMMAND_REJECTED"
    assert audit[-1]["rejection_reason"]["rule"] == "proposal-required-fields"


def test_direction_revision_blocks_child_until_experiment_reconfirmation(
    tmp_path,
):
    paths = _paths(tmp_path)
    project = project_node()
    direction = direction_node()
    experiment = experiment_node()
    for node, gate in (
        (project, "USER_ONLY"),
        (direction, "USER_CROSS_MODEL_AUDIT"),
        (experiment, "AGENT_DEFERRED_ACK"),
    ):
        assert _commit_payload(
            tmp_path,
            {**node, "op": "create", "gate": gate},
        ).returncode == 0
    store = EventStore(paths)
    direction_event = next(
        event
        for event in reversed(store.events())
        if event["aggregate_type"] == "direction"
        and event["aggregate_id"] == direction["id"]
    )
    management.commit_package_create(
        paths,
        {
            "id": "pkg",
            "lifecycle": "ACTIVE",
            "phase": "CONTEXT_LOADED",
            "blocker": None,
            "problem": "The current retrieval workflow has no validated transfer path.",
            "motivation": (
                "A matched comparison can test whether shared structure enables transfer."
            ),
            "objective": (
                "Collect bounded evidence that determines whether transfer is realized."
            ),
            "hypothesis": direction["spec"]["hypothesis"],
            "direction_id": direction["id"],
            "sourceVersion": 1,
            "sourceChange": direction_event["event_id"],
            "sourceExperiments": [
                {
                    "id": experiment["id"],
                    "version": 1,
                    "source": experiment["source"],
                }
            ],
        },
        [
            {
                "scope_experiment_id": experiment["id"],
                "local_id": "P0",
                "status": "READY",
            }
        ],
    )
    revised_direction = {
        **direction,
        "version": 2,
        "spec": direction_spec(
            success_gate=(
                "Recall at ten must improve by at least three absolute points "
                "over the declared baseline on the held out evaluation split."
            )
        ),
        "source": "triage:direction-v2",
        "op": "revise",
        "gate": "USER_CROSS_MODEL_AUDIT",
    }

    revised = _commit_payload(tmp_path, revised_direction)

    assert revised.returncode == 0, revised.stdout + revised.stderr
    stale = store.state()["aggregates"]["experiment"][experiment["id"]]
    assert stale["scope_confirmation"] == "STALE"
    assert stale["status"] == "BLOCKED"
    assert stale["status_before_scope_stale"] == "READY"
    assert stale["stale_direction_version"] == 2
    with pytest.raises(CommandRejected, match="reconfirmed"):
        StateQuery(paths).context("pkg")

    reconfirmed_experiment = {
        **experiment,
        "version": 2,
        "source": "triage:experiment-v2",
        "op": "revise",
        "gate": "AGENT_DEFERRED_ACK",
    }
    reconfirmed = _commit_payload(tmp_path, reconfirmed_experiment)

    assert reconfirmed.returncode == 0, reconfirmed.stdout + reconfirmed.stderr
    current = store.state()["aggregates"]["experiment"][experiment["id"]]
    assert current["scope_confirmation"] == "CONFIRMED"
    assert current["confirmed_direction_version"] == 2
    assert current["status"] == "READY"
    assert StateQuery(paths).context("pkg")["data"]["selection"]["package"]["id"] == "pkg"


def test_accepted_experiment_proposal_is_bound_to_direction_version(tmp_path):
    paths = _paths(tmp_path)
    project = project_node()
    direction = direction_node()
    for node, gate in (
        (project, "USER_ONLY"),
        (direction, "USER_CROSS_MODEL_AUDIT"),
    ):
        result = _commit_payload(
            tmp_path,
            {**node, "op": "create", "gate": gate},
        )
        assert result.returncode == 0, result.stdout + result.stderr

    experiment = experiment_node()
    experiment_payload = {
        **experiment,
        "op": "create",
        "gate": "AGENT_DEFERRED_ACK",
    }
    item = _proposal_item(
        experiment_payload,
        item_id="proposal-experiment-stale-parent",
    )
    management.submit_proposal(paths, item)
    pending = next(
        row
        for row in management.pending_proposals(paths)
        if row["id"] == item["id"]
    )
    assert pending["parent_scope_version"] == 1
    management.dispose_proposal(
        paths,
        item["id"],
        "ACCEPTED",
        pending["proposal_hash"],
        actor={"type": "user", "id": "test-pm"},
    )
    accepted_payload, causation_id = management.accepted_scope_payload(
        paths,
        item["id"],
    )

    revised_direction = {
        **direction,
        "version": 2,
        "source": "triage:direction-v2-before-experiment",
        "op": "revise",
        "gate": "USER_CROSS_MODEL_AUDIT",
    }
    revised = _commit_payload(tmp_path, revised_direction)
    assert revised.returncode == 0, revised.stdout + revised.stderr

    with pytest.raises(CommandRejected) as rejected:
        management.commit_scope_transition(
            paths,
            accepted_payload,
            causation_id=causation_id,
        )
    assert rejected.value.rule == "accepted-proposal-parent-stale"
    assert (
        experiment["id"]
        not in EventStore(paths).state()["aggregates"]["experiment"]
    )
