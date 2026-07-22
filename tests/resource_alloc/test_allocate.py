import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib import resource_alloc as ra  # noqa: E402
from lib.resource_alloc import allocate as alc  # noqa: E402
from lib.resource_alloc import probe  # noqa: E402
from lib.research_state.store import EventStore  # noqa: E402


def _seed(tmp_path):
    ra.register_server(tmp_path, {"name": "local", "kind": "local",
                                  "gpus": [{"type": "a6000", "count": 2, "mem_gb": 48}]})
    ra.register_server(tmp_path, {"name": "nectar", "kind": "ssh",
                                  "control": {"path": "direct", "host": "203.0.113.7"},
                                  "gpus": [{"type": "a100", "count": 1, "mem_gb": 40}]})
    ra.register_server(tmp_path, {"name": "bunya", "kind": "slurm",
                                  "control": {"path": "tmux", "tmux_session": "bunya"},
                                  "gpus": [{"type": "h100", "count": 3, "mem_gb": 80}],
                                  "slurm": {"account": "a_eecs_ds", "max_hours": 168},
                                  "tags": ["msrvtt-features"]})
    store = EventStore(ra.research_paths(tmp_path), fixture_mode=True)
    store.commit(
        event_type="AggregateImported",
        aggregate_type="package",
        aggregate_id="2026-06-12-demo",
        payload={
            "record": {
                "id": "2026-06-12-demo",
                "direction_id": "direction/demo",
                "lifecycle": "ACTIVE",
                "phase": "READY_TO_LAUNCH",
                "blocker": None,
            },
            "migration": {"source": "test-fixture"},
        },
        actor={"type": "system", "id": "test"},
        idempotency_key="test-package",
    )
    store.commit(
        event_type="AggregateImported",
        aggregate_type="experiment",
        aggregate_id="experiment/demo/P1",
        payload={
            "record": {
                "id": "experiment/demo/P1",
                "package_id": "2026-06-12-demo",
                "local_id": "P1",
                "direction_id": "direction/demo",
                "status": "READY",
                "spec": {
                    "purpose": "Exercise resource allocation.",
                    "config_ref": "configs/test.yaml",
                    "gate": "allocation is recorded",
                    "control_mode": "CHECKPOINTED",
                },
            },
            "migration": {"source": "test-fixture"},
        },
        actor={"type": "system", "id": "test"},
        idempotency_key="test-experiment",
    )


def _req(**over):
    base = {"pkg": "2026-06-12-demo", "exp_id": "P1"}
    base.update(over)
    return base


def _authorize_run(
    tmp_path,
    allocation,
    *,
    run_id="P1-20260612-101500",
    package_id="2026-06-12-demo",
    experiment_id="experiment/demo/P1",
    alloc_id=None,
):
    store = EventStore(ra.research_paths(tmp_path))
    store.commit(
        event_type="RunLaunchAuthorized",
        aggregate_type="run",
        aggregate_id=run_id,
        payload={
            "record": {
                "id": run_id,
                "package_id": package_id,
                "experiment_id": experiment_id,
                "dir": f"experiments/{package_id}/P1/{run_id}",
                "resource": {
                    "server": allocation["server"],
                    "alloc_id": allocation["alloc_id"] if alloc_id is None else alloc_id,
                },
            }
        },
        actor={"type": "agent", "id": "test"},
        entry_skill="research-run",
        idempotency_key=f"test-run-authorized:{run_id}",
        expected_version=0,
    )
    return store


def test_recommend_ranks_unknown_availability_by_start_latency(tmp_path):
    _seed(tmp_path)
    out = alc.recommend(tmp_path, _req())
    names = [c["server"] for c in out["candidates"]]
    assert names == ["local", "nectar", "bunya"]
    assert all(c["availability"] == "unknown" for c in out["candidates"])
    assert all(c["reasons"] for c in out["candidates"])


def test_recommend_confirmed_free_beats_lower_latency_unknown(tmp_path):
    _seed(tmp_path)
    gpus = probe.parse_nvidia_smi("0, 100, 81920, 0\n1, 100, 81920, 0\n2, 100, 81920, 0\n")
    probe.write_snapshot(tmp_path, "bunya", gpus, t=1000.0)

    out = alc.recommend(tmp_path, _req(), now=1010.0)
    assert out["candidates"][0]["server"] == "bunya"
    assert out["candidates"][0]["availability"] == "confirmed-free"


def test_recommend_hard_filters_with_reasons(tmp_path):
    _seed(tmp_path)
    out = alc.recommend(tmp_path, _req(tags=["msrvtt-features"], min_hours=24))
    assert [c["server"] for c in out["candidates"]] == ["bunya"]
    blocked = {b["server"]: " ".join(b["reasons"]) for b in out["blocked"]}
    assert "tag" in blocked["local"]
    assert "tag" in blocked["nectar"]

    out = alc.recommend(tmp_path, _req(gpu_type="h100"))
    assert [c["server"] for c in out["candidates"]] == ["bunya"]

    out = alc.recommend(tmp_path, _req(min_mem_gb=60))
    assert [c["server"] for c in out["candidates"]] == ["bunya"]

    out = alc.recommend(tmp_path, _req(gpu_count=2))
    assert "nectar" in {b["server"] for b in out["blocked"]}


def test_recommend_excludes_disabled_and_respects_max_hours(tmp_path):
    _seed(tmp_path)
    ra.register_server(tmp_path, {"name": "nectar", "kind": "ssh", "status": "DISABLED",
                                  "control": {"path": "direct", "host": "203.0.113.7"},
                                  "gpus": [{"type": "a100", "count": 1, "mem_gb": 40}]})
    ra.register_server(tmp_path, {"name": "bunya", "kind": "slurm",
                                  "control": {"path": "tmux", "tmux_session": "bunya"},
                                  "gpus": [{"type": "h100", "count": 3, "mem_gb": 80}],
                                  "slurm": {"account": "a_eecs_ds", "max_hours": 1}})

    out = alc.recommend(tmp_path, _req(min_hours=24))
    servers = {c["server"] for c in out["candidates"]}
    assert "nectar" not in servers
    assert "bunya" not in servers
    blocked = {b["server"]: " ".join(b["reasons"]) for b in out["blocked"]}
    assert "DISABLED" in blocked["nectar"]
    assert "max_hours" in blocked["bunya"]


def test_recommend_best_fit_prefers_smallest_sufficient_gpu(tmp_path):
    ra.register_server(tmp_path, {"name": "big", "kind": "ssh",
                                  "control": {"path": "direct", "host": "a"},
                                  "gpus": [{"type": "h100", "count": 1, "mem_gb": 80}]})
    ra.register_server(tmp_path, {"name": "small", "kind": "ssh",
                                  "control": {"path": "direct", "host": "b"},
                                  "gpus": [{"type": "a100", "count": 1, "mem_gb": 40}]})

    out = alc.recommend(tmp_path, _req(min_mem_gb=30))
    assert [c["server"] for c in out["candidates"]] == ["small", "big"]


def test_allocate_consumes_capacity_and_rejects_overbooking(tmp_path):
    _seed(tmp_path)
    entry = alc.allocate(tmp_path, "bunya", _req(gpu_type="h100", gpu_count=3), reason="sweep wave")
    assert entry["alloc_id"]
    assert entry["server"] == "bunya"
    assert entry["experiment_id"] == "experiment/demo/P1"
    assert entry["experiment_local_id"] == "P1"

    out = alc.recommend(tmp_path, _req(gpu_type="h100"))
    assert "bunya" in {b["server"] for b in out["blocked"]}

    before = (tmp_path / "state" / "events.jsonl").read_text(encoding="utf-8")
    with pytest.raises(ra.RuleViolation):
        alc.allocate(tmp_path, "bunya", _req(gpu_type="h100", gpu_count=1))
    assert (tmp_path / "state" / "events.jsonl").read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    ("gpu_ids", "rule"),
    [
        (["0"], "exactly gpu_count=2"),
        (["0", "0"], "must be unique"),
    ],
)
def test_allocate_rejects_gpu_ids_that_do_not_match_gpu_count(
    tmp_path,
    gpu_ids,
    rule,
):
    _seed(tmp_path)
    before = EventStore(ra.research_paths(tmp_path)).state()["source_seq"]
    with pytest.raises(ra.RuleViolation, match=rule):
        alc.allocate(
            tmp_path,
            "local",
            _req(gpu_count=2),
            gpu_ids=gpu_ids,
        )
    assert EventStore(ra.research_paths(tmp_path)).state()["source_seq"] == before


def test_allocate_normalizes_explicit_gpu_ids(tmp_path):
    _seed(tmp_path)
    entry = alc.allocate(
        tmp_path,
        "local",
        _req(gpu_count=2),
        gpu_ids=[" 0", "1 "],
    )
    assert entry["gpu_ids"] == ["0", "1"]


def test_allocate_assigns_deterministic_nonoverlapping_physical_ids(tmp_path):
    _seed(tmp_path)

    first = alc.allocate(tmp_path, "local", _req(gpu_count=1))
    second = alc.allocate(tmp_path, "local", _req(gpu_count=1))

    assert first["gpu_type"] == "a6000"
    assert second["gpu_type"] == "a6000"
    assert first["gpu_ids"] == ["0"]
    assert second["gpu_ids"] == ["1"]


def test_allocate_rejects_explicit_physical_id_overlap_and_audits(tmp_path):
    _seed(tmp_path)
    first = alc.allocate(
        tmp_path,
        "local",
        _req(gpu_type="a6000", gpu_count=1),
        gpu_ids=["1"],
    )
    store = EventStore(ra.research_paths(tmp_path))
    before_seq = store.state()["source_seq"]
    secret_reason = "allocation-secret-must-not-enter-audit"

    with pytest.raises(ra.RuleViolation, match="already allocated"):
        alc.allocate(
            tmp_path,
            "local",
            _req(gpu_type="a6000", gpu_count=1),
            gpu_ids=["1"],
            reason=secret_reason,
        )

    assert first["gpu_ids"] == ["1"]
    assert store.state()["source_seq"] == before_seq
    audit = [
        json.loads(line)
        for line in store.paths.audit_actions.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["outcome"] for row in audit[-1:]] == ["COMMAND_REJECTED"]
    assert audit[-1]["rejection_reason"]["rule"] == "resource-gpu-placement"
    assert secret_reason not in store.paths.audit_actions.read_text(
        encoding="utf-8"
    )


def test_same_physical_id_is_scoped_by_server_and_gpu_type(tmp_path):
    _seed(tmp_path)
    ra.register_server(
        tmp_path,
        {
            "name": "mixed",
            "kind": "local",
            "gpus": [
                {"type": "h100", "count": 1, "ids": ["0"]},
                {"type": "a100", "count": 1, "ids": ["0"]},
            ],
        },
    )

    h100 = alc.allocate(
        tmp_path,
        "mixed",
        _req(gpu_type="h100"),
        gpu_ids=["0"],
    )
    a100 = alc.allocate(
        tmp_path,
        "mixed",
        _req(gpu_type="a100"),
        gpu_ids=["0"],
    )

    assert (h100["gpu_type"], h100["gpu_ids"]) == ("h100", ["0"])
    assert (a100["gpu_type"], a100["gpu_ids"]) == ("a100", ["0"])


def test_allocate_rejects_undeclared_physical_ids_before_event(tmp_path):
    _seed(tmp_path)
    store = EventStore(ra.research_paths(tmp_path))
    before_seq = store.state()["source_seq"]

    with pytest.raises(ra.RuleViolation, match="not declared/eligible"):
        alc.allocate(
            tmp_path,
            "local",
            _req(gpu_type="a6000"),
            gpu_ids=["9"],
        )

    assert store.state()["source_seq"] == before_seq


def test_allocate_unknown_server_rejects(tmp_path):
    _seed(tmp_path)
    with pytest.raises(ra.RuleViolation):
        alc.allocate(tmp_path, "ghost", _req())


def test_link_release_lifecycle(tmp_path):
    _seed(tmp_path)
    entry = alc.allocate(tmp_path, "local", _req())
    _authorize_run(tmp_path, entry)
    alc.link(tmp_path, entry["alloc_id"], run_id="P1-20260612-101500")

    released = alc.release(tmp_path, entry["alloc_id"], outcome="COMPLETED")
    assert released["outcome"] == "COMPLETED"
    assert ra.open_allocations(tmp_path) == []

    with pytest.raises(ra.RuleViolation):
        alc.release(tmp_path, entry["alloc_id"], outcome="COMPLETED")
    with pytest.raises(ra.RuleViolation):
        alc.release(tmp_path, "never-existed", outcome="COMPLETED")


@pytest.mark.parametrize(
    ("run_id", "package_id", "experiment_id", "alloc_id", "match"),
    [
        ("missing-run", None, None, None, "authorized run"),
        (
            "wrong-package",
            "another-package",
            "experiment/demo/P1",
            None,
            "another package",
        ),
        (
            "wrong-experiment",
            "2026-06-12-demo",
            "experiment/other/P9",
            None,
            "another Experiment",
        ),
        (
            "wrong-allocation",
            "2026-06-12-demo",
            "experiment/demo/P1",
            "a-different-allocation",
            "not authorized",
        ),
    ],
)
def test_link_rejects_unmatched_run_identity(
    tmp_path,
    run_id,
    package_id,
    experiment_id,
    alloc_id,
    match,
):
    _seed(tmp_path)
    entry = alc.allocate(tmp_path, "local", _req())
    if package_id is not None:
        _authorize_run(
            tmp_path,
            entry,
            run_id=run_id,
            package_id=package_id,
            experiment_id=experiment_id,
            alloc_id=alloc_id,
        )
    before = len(EventStore(ra.research_paths(tmp_path)).events())

    with pytest.raises(ra.RuleViolation, match=match):
        alc.link(tmp_path, entry["alloc_id"], run_id=run_id)

    store = EventStore(ra.research_paths(tmp_path))
    assert len(store.events()) == before
    assert store.state()["aggregates"]["resource_allocation"][
        entry["alloc_id"]
    ].get("run_id") is None
    assert "COMMAND_REJECTED" in store.paths.audit_actions.read_text(
        encoding="utf-8"
    )


def test_link_requires_run_or_job_target(tmp_path):
    _seed(tmp_path)
    entry = alc.allocate(tmp_path, "local", _req())

    with pytest.raises(ra.RuleViolation, match="run_id or job_id"):
        alc.link(tmp_path, entry["alloc_id"])


def test_job_link_keeps_allocation_experiment_identity(tmp_path):
    _seed(tmp_path)
    entry = alc.allocate(tmp_path, "local", _req())

    alc.link(tmp_path, entry["alloc_id"], job_id="job-123")

    allocation = EventStore(ra.research_paths(tmp_path)).state()["aggregates"][
        "resource_allocation"
    ][entry["alloc_id"]]
    assert allocation["job_id"] == "job-123"
    assert allocation["package_id"] == "2026-06-12-demo"
    assert allocation["experiment_id"] == "experiment/demo/P1"


def test_status_reports_occupancy_and_flags_leaked_allocations(tmp_path):
    _seed(tmp_path)
    entry = alc.allocate(tmp_path, "local", _req())
    store = _authorize_run(tmp_path, entry)
    alc.link(tmp_path, entry["alloc_id"], run_id="P1-20260612-101500")
    common = {
        "aggregate_type": "run",
        "aggregate_id": "P1-20260612-101500",
        "actor": {"type": "agent", "id": "test"},
        "entry_skill": "research-run",
    }
    store.commit(
        **common,
        event_type="RunLaunched",
        payload={"patch": {}},
        idempotency_key="test-run-launched",
        expected_version=1,
    )
    store.commit(
        **common,
        event_type="RunTerminal",
        payload={"status": "COMPLETED", "patch": {}},
        idempotency_key="test-run-terminal",
        expected_version=2,
    )

    report = alc.status(tmp_path)
    local_row = next(s for s in report["servers"] if s["name"] == "local")
    assert local_row["open_allocations"] == 1
    assert [leak["alloc_id"] for leak in report["leaks"]] == [entry["alloc_id"]]

    alc.release(tmp_path, entry["alloc_id"], outcome="COMPLETED")
    assert alc.status(tmp_path)["leaks"] == []
