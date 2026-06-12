import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib import resource_alloc as ra  # noqa: E402
from lib.resource_alloc import allocate as alc  # noqa: E402
from lib.resource_alloc import probe  # noqa: E402


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


def _req(**over):
    base = {"pkg": "2026-06-12-demo", "exp_id": "P1"}
    base.update(over)
    return base


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

    out = alc.recommend(tmp_path, _req(gpu_type="h100"))
    assert "bunya" in {b["server"] for b in out["blocked"]}

    before = (tmp_path / "_resources" / "allocations.jsonl").read_text(encoding="utf-8")
    with pytest.raises(ra.RuleViolation):
        alc.allocate(tmp_path, "bunya", _req(gpu_type="h100", gpu_count=1))
    assert (tmp_path / "_resources" / "allocations.jsonl").read_text(encoding="utf-8") == before


def test_allocate_unknown_server_rejects(tmp_path):
    _seed(tmp_path)
    with pytest.raises(ra.RuleViolation):
        alc.allocate(tmp_path, "ghost", _req())


def test_link_release_lifecycle(tmp_path):
    _seed(tmp_path)
    entry = alc.allocate(tmp_path, "local", _req())
    alc.link(tmp_path, entry["alloc_id"], run_id="P1-20260612-101500")

    released = alc.release(tmp_path, entry["alloc_id"], outcome="COMPLETED")
    assert released["outcome"] == "COMPLETED"
    assert ra.open_allocations(tmp_path) == []

    with pytest.raises(ra.RuleViolation):
        alc.release(tmp_path, entry["alloc_id"], outcome="COMPLETED")
    with pytest.raises(ra.RuleViolation):
        alc.release(tmp_path, "never-existed", outcome="COMPLETED")


def test_status_reports_occupancy_and_flags_leaked_allocations(tmp_path):
    _seed(tmp_path)
    entry = alc.allocate(tmp_path, "local", _req())
    alc.link(tmp_path, entry["alloc_id"], run_id="P1-20260612-101500")

    live = tmp_path / "_live" / "runs.jsonl"
    live.parent.mkdir(parents=True)
    live.write_text(
        json.dumps({"op": "launched", "run_id": "P1-20260612-101500", "pkg": "2026-06-12-demo"}) + "\n"
        + json.dumps({"op": "terminal", "run_id": "P1-20260612-101500", "final_status": "COMPLETED"}) + "\n",
        encoding="utf-8",
    )

    report = alc.status(tmp_path)
    local_row = next(s for s in report["servers"] if s["name"] == "local")
    assert local_row["open_allocations"] == 1
    assert [leak["alloc_id"] for leak in report["leaks"]] == [entry["alloc_id"]]

    alc.release(tmp_path, entry["alloc_id"], outcome="COMPLETED")
    assert alc.status(tmp_path)["leaks"] == []
