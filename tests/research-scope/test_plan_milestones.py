import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-scope" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

import plan_milestones  # noqa: E402
from lib.research_state import EventStore, ResearchPaths, StateQuery  # noqa: E402
import management  # noqa: E402
import triage  # noqa: E402
from tests.scope_fixtures import (  # noqa: E402
    commit_accepted_scope,
    direction_node,
    project_node,
)


def _direction_node():
    return direction_node(version=1, source="accepted:t1")


def _paths(tmp_path):
    return ResearchPaths.resolve(workspace=tmp_path)


def _write_direction(paths):
    commit_accepted_scope(management, paths, project_node())
    commit_accepted_scope(management, paths, _direction_node())


def _contracts_json():
    return json.dumps([
        {
            "slug": "E0-reproduction-characterization",
            "purpose": "Record the released checkpoint evaluation behavior under the declared dataset and protocol, including configuration, coverage, metrics, provenance, and observed discrepancies for later review.",
            "config_ref": "scope:dir/retrieval-v2@1#e0-reproduction-v1",
            "gate": "Complete the declared evaluation and preserve configuration, coverage, metrics, logs, artifact provenance, and discrepancy notes; no agreement or performance threshold controls evidence admission.",
            "control_mode": "CHECKPOINTED",
        },
        {
            "slug": "E1-transfer-characterization",
            "purpose": "Run the transferred method and declared comparison arms under one fixed retrieval and evaluation protocol, recording effectiveness, behavior, cost, and provenance for paired review.",
            "config_ref": "scope:dir/retrieval-v2@1#e1-transfer-v1",
            "gate": "Complete the declared arms and seeds and preserve coverage, paired metrics, diagnostics, costs, logs, configuration, and provenance; no improvement threshold controls evidence admission.",
            "control_mode": "CHECKPOINTED",
        },
    ])


def test_plan_milestones_writes_pending_experiment_proposals_only(tmp_path):
    paths = _paths(tmp_path)
    _write_direction(paths)

    rc = plan_milestones.main([
        "--workspace", str(tmp_path),
        "--direction-id", "dir/retrieval-v2",
        "--contracts-json", _contracts_json(),
    ])

    assert rc == 0
    pending = triage.pending(paths)
    assert len(pending) == 2
    assert all(item["level"] == "experiment" for item in pending)
    assert all(item["gate"] == "AGENT_DEFERRED_ACK" for item in pending)
    assert pending[0]["proposed_node"]["parents"] == ["dir/retrieval-v2"]
    assert pending[0]["proposed_node"]["spec"]["control_mode"] == "CHECKPOINTED"
    assert pending[0]["proposed_node"]["spec"]["config_ref"].startswith("scope:")
    assert pending[0]["proposed_node"]["id"].endswith(
        "/e0-reproduction-characterization"
    )

    state = EventStore(paths).state()
    assert list(state["aggregates"]["direction"]) == ["dir/retrieval-v2"]
    assert state["aggregates"]["experiment"] == {}


def test_plan_milestones_dry_run_does_not_write_triage(tmp_path, capsys):
    paths = _paths(tmp_path)
    _write_direction(paths)
    before = StateQuery(paths).show("proposal")["data"]

    rc = plan_milestones.main([
        "--workspace", str(tmp_path),
        "--direction-id", "dir/retrieval-v2",
        "--contracts-json", _contracts_json(),
        "--dry-run",
    ])

    assert rc == 0
    proposals = json.loads(capsys.readouterr().out)
    assert len(proposals) == 2
    assert StateQuery(paths).show("proposal")["data"] == before


def test_accepted_validation_proposal_commits_canonical_experiment(tmp_path):
    paths = _paths(tmp_path)
    _write_direction(paths)
    plan_milestones.main([
        "--workspace", str(tmp_path),
        "--direction-id", "dir/retrieval-v2",
        "--contracts-json", _contracts_json(),
    ])
    item = triage.pending(paths)[0]
    triage.dispose(
        paths,
        item["id"],
        "ACCEPTED",
        item["proposal_hash"],
        actor={"type": "user", "id": "test-pm"},
    )
    payload, causation_id = management.accepted_scope_payload(
        paths,
        item["id"],
    )
    management.commit_scope_transition(
        paths,
        payload,
        causation_id=causation_id,
    )

    experiment = StateQuery(paths).show(
        "experiment",
        item["proposed_node"]["id"],
    )["data"]
    assert set(experiment["spec"]) == {
        "purpose",
        "config_ref",
        "gate",
        "control_mode",
    }
    assert experiment["direction_id"] == "dir/retrieval-v2"
    assert "source_task" not in experiment
    assert "after" not in experiment


def test_plan_milestones_rejects_pending_only_direction(tmp_path):
    paths = _paths(tmp_path)
    node = _direction_node()
    triage.propose(
        paths,
        {
            "id": "t1",
            "level": "direction",
            "node_id": node["id"],
            "op": "create",
            "gate": "USER_CROSS_MODEL_AUDIT",
            "proposed_spec": node["spec"],
            "proposed_node": node,
        },
    )

    with pytest.raises(SystemExit, match="Committed Direction not found"):
        plan_milestones.main([
            "--workspace", str(tmp_path),
            "--direction-id", "dir/retrieval-v2",
            "--contracts-json", _contracts_json(),
        ])


def test_plan_milestones_requires_explicit_evidence_contracts(tmp_path):
    paths = _paths(tmp_path)
    _write_direction(paths)

    with pytest.raises(SystemExit, match="2"):
        plan_milestones.main([
            "--workspace", str(tmp_path),
            "--direction-id", "dir/retrieval-v2",
        ])


def test_plan_milestones_rejects_non_scope_contract_fields(tmp_path):
    paths = _paths(tmp_path)
    _write_direction(paths)
    contracts = json.loads(_contracts_json())
    contracts[0]["after"] = "evidence/e-previous"

    with pytest.raises(SystemExit, match=r"unknown fields: \['after'\]"):
        plan_milestones.main([
            "--workspace", str(tmp_path),
            "--direction-id", "dir/retrieval-v2",
            "--contracts-json", json.dumps(contracts),
        ])
