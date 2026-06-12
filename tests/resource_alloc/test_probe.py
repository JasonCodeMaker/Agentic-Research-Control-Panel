import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.resource_alloc import probe  # noqa: E402

NVSMI_MIXED = """\
0, 11264, 81920, 96
1, 3, 81920, 0
2, 80000, 81920, 100
"""


def test_parse_nvidia_smi_marks_free_gpus():
    gpus = probe.parse_nvidia_smi(NVSMI_MIXED)
    assert [g["index"] for g in gpus] == [0, 1, 2]
    assert [g["free"] for g in gpus] == [False, True, False]
    assert gpus[1]["mem_total_gb"] == 80.0
    assert gpus[0]["util"] == 96


def test_parse_nvidia_smi_skips_garbage_lines():
    text = "NVIDIA-SMI has failed\n" + NVSMI_MIXED + "not,a,gpu,line,x\n\n"
    gpus = probe.parse_nvidia_smi(text)
    assert len(gpus) == 3


def test_snapshot_write_and_fresh_load(tmp_path):
    gpus = probe.parse_nvidia_smi(NVSMI_MIXED)
    path = probe.write_snapshot(tmp_path, "bunya", gpus, t=1000.0)
    assert path == tmp_path / "_resources" / "snapshots" / "bunya.json"
    json.loads(path.read_text(encoding="utf-8"))

    snap = probe.load_snapshot(tmp_path, "bunya", now=1100.0)
    assert snap["fresh"] is True
    assert snap["free_count"] == 1


def test_snapshot_goes_stale_and_missing_is_none(tmp_path):
    gpus = probe.parse_nvidia_smi(NVSMI_MIXED)
    probe.write_snapshot(tmp_path, "bunya", gpus, t=1000.0)

    stale = probe.load_snapshot(tmp_path, "bunya", now=1000.0 + probe.SNAPSHOT_MAX_AGE + 1)
    assert stale["fresh"] is False

    assert probe.load_snapshot(tmp_path, "nectar", now=0.0) is None
