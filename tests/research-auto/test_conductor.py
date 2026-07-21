"""State-backed contracts for the autonomous Direction campaign conductor."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PIPELINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PIPELINE / "skills" / "research-auto" / "scripts"))
sys.path.insert(0, str(PIPELINE))
sys.path.insert(0, str(PIPELINE / "lib"))

import conductor  # noqa: E402
from lib.research_state import EventStore, ResearchPaths  # noqa: E402


ACTOR = {"type": "agent", "id": "test"}
DIRECTION_ID = "dir/d1"
PACKAGE_ID = "2026-06-12-d1"
EXPERIMENT_ID = "experiment/d1/e1"
LEGACY_EXPERIMENT_ID = f"{PACKAGE_ID}::P1"
RUN_ID = "run-p1"


def _paths(tmp_path: Path) -> ResearchPaths:
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    EventStore(paths).initialize()
    return paths


def _upsert(
    store: EventStore,
    aggregate_type: str,
    aggregate_id: str,
    record: dict,
) -> None:
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload={"record": record},
        actor=ACTOR,
        idempotency_key=f"seed:{aggregate_type}:{aggregate_id}",
        expected_version=0,
    )


def _seed_direction(paths: ResearchPaths) -> None:
    _upsert(
        EventStore(paths, migration_mode=True),
        "direction",
        DIRECTION_ID,
        {
            "id": DIRECTION_ID,
            "level": "direction",
            "parents": ["project/p1"],
            "version": 1,
            "status": "ACTIVE",
            "spec": {
                "hypothesis": "A controlled reranker can improve retrieval quality.",
                "metric": {"name": "R@1"},
                "baselines": ["frozen baseline"],
                "success_gate": "R@1 >= 48 on the held-out split",
            },
            "source": "test",
        },
    )


def _seed_package(paths: ResearchPaths, *, executable: bool = True) -> None:
    store = EventStore(paths)
    scope_store = EventStore(paths, migration_mode=True)
    _upsert(
        store,
        "package",
        PACKAGE_ID,
        {
            "id": PACKAGE_ID,
            "slug": PACKAGE_ID,
            "direction_id": DIRECTION_ID,
            "sourceDirection": DIRECTION_ID,
            "sourceVersion": 1,
            "sourceChange": "test",
            "sourceExperiments": [
                {
                    "id": EXPERIMENT_ID,
                    "version": 1,
                    "source": "test",
                }
            ],
            "lifecycle": "ACTIVE",
            "phase": "READY_TO_LAUNCH",
            "blocker": None,
        },
    )
    _upsert(
        scope_store,
        "experiment",
        EXPERIMENT_ID,
        {
            "id": EXPERIMENT_ID,
            "local_id": "P1",
            "package_id": PACKAGE_ID,
            "direction_id": DIRECTION_ID,
            "aliases": ["P1", LEGACY_EXPERIMENT_ID],
            "spec": {
                "purpose": "Measure whether the controlled reranker clears the gate.",
                "config_ref": "configs/p1.yaml",
                "gate": "R@1 >= 48",
                "control_mode": "AUTONOMOUS",
            },
            "status": "READY" if executable else "COMPLETE",
            "scope_status": "ACTIVE",
            "scope_confirmation": "CONFIRMED",
            "scope_version": 1,
            "scope_source": "test",
            "confirmed_direction_version": 1,
        },
    )


def _seed_terminal_run(
    paths: ResearchPaths,
    *,
    experiment_id: str = EXPERIMENT_ID,
) -> None:
    _upsert(
        EventStore(paths),
        "run",
        RUN_ID,
        {
            "id": RUN_ID,
            "package_id": PACKAGE_ID,
            "experiment_id": experiment_id,
            "status": "COMPLETED",
        },
    )


def _cycle_record(**overrides) -> dict:
    record = {
        "cycle": 1,
        "direction_id": DIRECTION_ID,
        "pkg_id": PACKAGE_ID,
        "exp_id": "P1",
        "run_id": RUN_ID,
        "hypothesis": "The controlled reranker improves retrieval.",
        "verdict": "FAIL",
        "measured": "46.1",
        "gate_eval": "FAIL",
        "evidence": "experiments/2026-06-12-d1/P1/run-p1/result.json",
        "next_action": "DESIGN_EXPERIMENT",
    }
    record.update(overrides)
    return record


@pytest.mark.parametrize(
    ("gate", "expected"),
    [
        ("R@1 >= 48 on held-out seed", {"cmp": ">=", "threshold": 48.0}),
        ("val loss <= 0.5", {"cmp": "<=", "threshold": 0.5}),
        ("accuracy > 0.8", {"cmp": ">", "threshold": 0.8}),
        ("latency < 120", {"cmp": "<", "threshold": 120.0}),
    ],
)
def test_parse_gate(gate, expected):
    assert conductor.parse_gate(gate) == expected


def test_parse_gate_unparseable_raises():
    with pytest.raises(conductor.GateUnparseable):
        conductor.parse_gate("beats the baseline convincingly")


def test_evaluate_gate():
    assert conductor.evaluate_gate(48.2, "R@1 >= 48") == "PASS"
    assert conductor.evaluate_gate("47.9", "R@1 >= 48") == "FAIL"
    assert conductor.evaluate_gate(0.4, "loss <= 0.5") == "PASS"


@pytest.mark.parametrize(
    "record",
    [
        _cycle_record(measured=""),
        _cycle_record(evidence="  "),
        _cycle_record(verdict="WIN"),
        _cycle_record(gate_eval="MAYBE"),
        _cycle_record(verdict="INCONCLUSIVE", gate_eval="PASS"),
        _cycle_record(next_action="MOVE_GOALPOST"),
    ],
)
def test_append_cycle_rejects_invalid_record_before_write(tmp_path, record):
    paths = _paths(tmp_path)
    with pytest.raises(ValueError):
        conductor.append_cycle(paths, DIRECTION_ID, record)
    assert EventStore(paths).state()["aggregates"]["campaign"] == {}


def test_append_cycle_requires_terminal_run_witness(tmp_path):
    paths = _paths(tmp_path)
    _seed_direction(paths)
    _seed_package(paths)
    with pytest.raises(ValueError, match="run does not exist"):
        conductor.append_cycle(paths, DIRECTION_ID, _cycle_record())


def test_append_and_query_cycle_roundtrip(tmp_path):
    paths = _paths(tmp_path)
    _seed_direction(paths)
    _seed_package(paths)
    _seed_terminal_run(paths)
    written = conductor.append_cycle(paths, DIRECTION_ID, _cycle_record())
    assert written["ts"]
    assert conductor.campaign_cycles(paths, DIRECTION_ID) == [written]
    campaign = EventStore(paths).state()["aggregates"]["campaign"][DIRECTION_ID]
    assert campaign["status"] == "RUNNING"
    assert campaign["route"] == "DESIGN_EXPERIMENT"


def test_append_cycle_accepts_migrated_run_experiment_alias(tmp_path):
    paths = _paths(tmp_path)
    _seed_direction(paths)
    _seed_package(paths)
    _seed_terminal_run(paths, experiment_id=LEGACY_EXPERIMENT_ID)
    written = conductor.append_cycle(paths, DIRECTION_ID, _cycle_record())
    assert written["exp_id"] == "P1"


def test_append_cycle_fails_closed_on_bound_experiment_alias_collision(tmp_path):
    paths = _paths(tmp_path)
    _seed_direction(paths)
    _seed_package(paths)
    _upsert(
        EventStore(paths, migration_mode=True),
        "experiment",
        "experiment/d1/e2",
        {
            "id": "experiment/d1/e2",
            "local_id": "P1",
            "package_id": PACKAGE_ID,
            "direction_id": DIRECTION_ID,
            "aliases": ["P1"],
            "spec": {
                "purpose": "Ambiguous fixture.",
                "config_ref": "configs/p1-other.yaml",
                "gate": "R@1 >= 48",
                "control_mode": "AUTONOMOUS",
            },
            "status": "READY",
            "scope_status": "ACTIVE",
            "scope_confirmation": "CONFIRMED",
            "scope_version": 1,
            "scope_source": "test",
            "confirmed_direction_version": 1,
        },
    )
    _seed_terminal_run(paths)
    with pytest.raises(ValueError, match=r"found 2"):
        conductor.append_cycle(paths, DIRECTION_ID, _cycle_record())
    assert EventStore(paths).state()["aggregates"]["campaign"] == {}


def test_duplicate_cycle_is_idempotent_but_conflict_is_rejected(tmp_path):
    paths = _paths(tmp_path)
    _seed_direction(paths)
    _seed_package(paths)
    _seed_terminal_run(paths)
    first = conductor.append_cycle(paths, DIRECTION_ID, _cycle_record())
    assert conductor.append_cycle(paths, DIRECTION_ID, _cycle_record()) == first
    with pytest.raises(ValueError, match="already exists"):
        conductor.append_cycle(
            paths,
            DIRECTION_ID,
            _cycle_record(measured="47.0"),
        )


def test_campaign_status():
    assert conductor.campaign_status([], max_cycles=5) == {
        "cycles_used": 0,
        "gate_met": False,
        "budget_exhausted": False,
        "last": None,
    }
    rows = [
        _cycle_record(),
        _cycle_record(
            cycle=2,
            verdict="PASS",
            gate_eval="PASS",
            measured="48.4",
            next_action="SUCCESS_EXIT",
        ),
    ]
    status = conductor.campaign_status(rows, max_cycles=2)
    assert status["gate_met"] is True
    assert status["cycles_used"] == 2
    assert status["budget_exhausted"] is False


def _route(**overrides):
    values = {
        "direction_committed": True,
        "pending_direction": False,
        "status": conductor.campaign_status([], max_cycles=5),
        "open_pkg": PACKAGE_ID,
        "has_executable_exp": True,
        "no_candidate": False,
        "dial": "AUTONOMOUS",
        "gate_parseable": True,
    }
    values.update(overrides)
    return conductor.next_action(**values)


@pytest.mark.parametrize(
    ("overrides", "route"),
    [
        ({"direction_committed": False, "open_pkg": None}, "FORM_DIRECTION"),
        (
            {
                "direction_committed": False,
                "pending_direction": True,
                "open_pkg": None,
            },
            "AWAIT_RATIFICATION",
        ),
        ({"gate_parseable": False}, "ASK_USER"),
        ({"no_candidate": True}, "HALT_NO_CANDIDATE"),
        ({"open_pkg": None, "has_executable_exp": False}, "MATERIALIZE_PACKAGE"),
        ({}, "RUN_PACKAGE"),
        ({"has_executable_exp": False}, "DESIGN_EXPERIMENT"),
    ],
)
def test_router(overrides, route):
    action = _route(**overrides)
    assert action["type"] == route
    assert set(action["next_step"]) == {
        "type",
        "headline",
        "next_action",
        "offer",
        "awaits_user",
        "details",
    }


def test_router_success_and_budget_precedence():
    passed = conductor.campaign_status(
        [_cycle_record(verdict="PASS", gate_eval="PASS")],
        max_cycles=1,
    )
    failed = conductor.campaign_status([_cycle_record()], max_cycles=1)
    assert _route(status=passed)["type"] == "SUCCESS_EXIT"
    assert _route(status=failed)["type"] == "HALT_BUDGET"


def test_authority_guard_rejects_scope_or_disposition_smuggling():
    disposal = conductor.validate_campaign_action(
        {"type": "RUN_PACKAGE", "decision": "accept"}
    )
    assert disposal and disposal["rejected"]
    direction = conductor.validate_campaign_action(
        {
            "type": "DESIGN_EXPERIMENT",
            "dial": "AUTONOMOUS",
            "mutations": [
                {
                    "op": "scope-transition",
                    "payload": {
                        "level": "direction",
                        "gate": "USER_CROSS_MODEL_AUDIT",
                    },
                }
            ],
        }
    )
    assert direction and any("Project or Direction" in reason for reason in direction["reasons"])


def test_authority_guard_enforces_experiment_deferred_ack():
    base = {
        "type": "DESIGN_EXPERIMENT",
        "dial": "AUTONOMOUS",
        "mutations": [
            {
                "op": "scope-transition",
                "payload": {
                    "level": "experiment",
                    "gate": "AGENT_DEFERRED_ACK",
                    "deferred_ack": "Review the next experiment spec.",
                },
            }
        ],
    }
    assert conductor.validate_campaign_action(base) is None
    wrong_gate = json.loads(json.dumps(base))
    wrong_gate["mutations"][0]["payload"]["gate"] = "USER_ONLY"
    assert conductor.validate_campaign_action(wrong_gate)["rejected"]
    supervised = json.loads(json.dumps(base))
    supervised["dial"] = "SUPERVISED"
    assert conductor.validate_campaign_action(supervised)["rejected"]
    no_ack = json.loads(json.dumps(base))
    del no_ack["mutations"][0]["payload"]["deferred_ack"]
    assert conductor.validate_campaign_action(no_ack)["rejected"]


def test_detect_open_package_uses_state_only(tmp_path):
    paths = _paths(tmp_path)
    _seed_direction(paths)
    assert conductor.detect_open_package(paths, DIRECTION_ID) == (None, False)
    _seed_package(paths)
    assert conductor.detect_open_package(paths, DIRECTION_ID) == (PACKAGE_ID, True)


def test_cli_status_routes_from_state(tmp_path, capsys):
    paths = _paths(tmp_path)
    _seed_direction(paths)
    _seed_package(paths)
    assert (
        conductor.main(
            [
                "status",
                "--workspace",
                str(tmp_path),
                "--direction-id",
                DIRECTION_ID,
                "--max-cycles",
                "5",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["state"]["direction_committed"] is True
    assert output["state"]["open_pkg"] == PACKAGE_ID
    assert output["action"]["type"] == "RUN_PACKAGE"


def test_cli_status_awaits_matching_pending_proposal(tmp_path, capsys):
    paths = _paths(tmp_path)
    _upsert(
        EventStore(paths),
        "proposal",
        "direction-d1",
        {
            "id": "direction-d1",
            "disposition": "PENDING",
            "level": "direction",
            "proposed_node": {"id": DIRECTION_ID, "level": "direction"},
        },
    )
    conductor.main(
        [
            "status",
            "--workspace",
            str(tmp_path),
            "--direction-id",
            DIRECTION_ID,
            "--gate",
            "R@1 >= 48",
        ]
    )
    assert json.loads(capsys.readouterr().out)["action"]["type"] == "AWAIT_RATIFICATION"


def test_cli_append_cycle_and_pack_write_campaign_state(tmp_path, capsys):
    paths = _paths(tmp_path)
    _seed_direction(paths)
    _seed_package(paths)
    _seed_terminal_run(paths)
    conductor.main(
        [
            "append-cycle",
            "--workspace",
            str(tmp_path),
            "--direction-id",
            DIRECTION_ID,
            "--record",
            json.dumps(_cycle_record()),
        ]
    )
    capsys.readouterr()
    bundle = {
        "attempted": "cycle 1: controlled reranker",
        "found": "FAIL 46.1 vs >=48",
        "hypothesis_state": "The improvement remains unproven.",
        "next_action": "DESIGN_EXPERIMENT",
        "blocking_decision": "none",
    }
    conductor.main(
        [
            "pack",
            "--workspace",
            str(tmp_path),
            "--direction-id",
            DIRECTION_ID,
            "--bundle",
            json.dumps(bundle),
        ]
    )
    campaign = EventStore(paths).state()["aggregates"]["campaign"][DIRECTION_ID]
    assert campaign["cycles"][0]["run_id"] == RUN_ID
    assert campaign["packs"][0]["next_action"] == "DESIGN_EXPERIMENT"


def test_legacy_campaign_filesystem_helpers_are_absent():
    assert not hasattr(conductor, "ledger_path")
    assert not hasattr(conductor, "read_ledger")
    assert not hasattr(conductor, "milestone_task_node")
