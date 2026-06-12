import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib import resource_alloc as ra  # noqa: E402


def _server(**over):
    base = {
        "name": "bunya",
        "kind": "slurm",
        "control": {"path": "tmux", "tmux_session": "bunya"},
        "gpus": [{"type": "h100", "count": 3, "mem_gb": 80}],
        "slurm": {"account": "a_eecs_ds", "max_hours": 168},
        "tags": ["msrvtt-features"],
        "skill": "bunya-slurm-ops",
    }
    base.update(over)
    return base


def test_register_and_load_roundtrip(tmp_path):
    saved = ra.register_server(tmp_path, _server())
    assert saved["status"] == "ACTIVE"
    assert saved["start_latency"] == 2  # slurm default

    registry = ra.load_registry(tmp_path)
    assert [s["name"] for s in registry] == ["bunya"]
    path = tmp_path / "_resources" / "servers.json"
    assert path.exists()
    json.loads(path.read_text(encoding="utf-8"))


def test_register_upserts_by_name_and_keeps_order(tmp_path):
    ra.register_server(tmp_path, _server(name="local", kind="local", control={"path": "direct"}, slurm=None))
    ra.register_server(tmp_path, _server())
    ra.register_server(tmp_path, _server(tags=["msrvtt-features", "h100"]))

    registry = ra.load_registry(tmp_path)
    assert [s["name"] for s in registry] == ["local", "bunya"]
    assert registry[1]["tags"] == ["msrvtt-features", "h100"]


def test_kind_defaults_for_start_latency_and_control(tmp_path):
    local = ra.register_server(tmp_path, {"name": "local", "kind": "local"})
    assert local["start_latency"] == 0
    assert local["control"] == {"path": "direct"}

    nectar = ra.register_server(tmp_path, {"name": "nectar", "kind": "ssh", "control": {"path": "direct", "host": "203.0.113.7"}})
    assert nectar["start_latency"] == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "", "kind": "local"},
        {"name": "has space", "kind": "local"},
        {"name": "x", "kind": "cloud"},
        {"name": "x", "kind": "local", "status": "RETIRED"},
        {"name": "x", "kind": "slurm", "control": {"path": "tmux"}},  # tmux without session
        {"name": "x", "kind": "local", "control": {"path": "teleport"}},
        {"name": "x", "kind": "local", "gpus": [{"type": "a100"}]},  # count missing
        {"name": "x", "kind": "local", "gpus": [{"type": "a100", "count": 0}]},
        {"name": "x", "kind": "local", "frobnicate": True},  # unknown field
        {"name": "x", "kind": "local", "tags": "not-a-list"},
    ],
)
def test_validate_rejects_before_write(tmp_path, bad):
    with pytest.raises(ra.RuleViolation):
        ra.register_server(tmp_path, bad)
    assert not (tmp_path / "_resources" / "servers.json").exists()


def test_ledger_append_and_open_fold(tmp_path):
    ra.append_ledger(tmp_path, {"op": "allocate", "alloc_id": "a1", "server": "local", "gpu_count": 1, "t": 1.0})
    ra.append_ledger(tmp_path, {"op": "allocate", "alloc_id": "a2", "server": "bunya", "gpu_count": 2, "t": 2.0})
    ra.append_ledger(tmp_path, {"op": "release", "alloc_id": "a1", "outcome": "COMPLETED", "t": 3.0})

    open_allocs = ra.open_allocations(tmp_path)
    assert [a["alloc_id"] for a in open_allocs] == ["a2"]

    lines = (tmp_path / "_resources" / "allocations.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
