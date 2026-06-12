import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "lib" / "resource_alloc" / "cli.py"

NVSMI = "0, 100, 49152, 0\n1, 100, 49152, 0\n"


def _run(tmp_path, *args, stdin=None):
    result = subprocess.run(
        [sys.executable, str(CLI), "--outputs-root", str(tmp_path), *args],
        capture_output=True, text=True, input=stdin,
    )
    return result


def test_cli_register_list_recommend_allocate_release_roundtrip(tmp_path):
    server = {"name": "local", "kind": "local", "gpus": [{"type": "a6000", "count": 2, "mem_gb": 48}]}
    out = _run(tmp_path, "register", stdin=json.dumps(server))
    assert out.returncode == 0, out.stderr

    out = _run(tmp_path, "list")
    assert "local" in out.stdout

    smi = tmp_path / "smi.txt"
    smi.write_text(NVSMI, encoding="utf-8")
    out = _run(tmp_path, "snapshot", "--server", "local", "--from-nvidia-smi", str(smi))
    assert out.returncode == 0, out.stderr

    out = _run(tmp_path, "recommend", "--pkg", "demo", "--exp", "P1", "--gpu-count", "1")
    assert out.returncode == 0, out.stderr
    rec = json.loads(out.stdout)
    assert rec["candidates"][0]["server"] == "local"
    assert rec["candidates"][0]["availability"] == "confirmed-free"

    out = _run(tmp_path, "allocate", "--server", "local", "--pkg", "demo", "--exp", "P1",
               "--gpu-count", "1", "--reason", "smoke")
    assert out.returncode == 0, out.stderr
    alloc_id = json.loads(out.stdout)["alloc_id"]

    out = _run(tmp_path, "link", "--alloc", alloc_id, "--run-id", "P1-20260612-101500")
    assert out.returncode == 0, out.stderr

    out = _run(tmp_path, "status")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["servers"][0]["open_allocations"] == 1

    out = _run(tmp_path, "release", "--alloc", alloc_id, "--outcome", "COMPLETED")
    assert out.returncode == 0, out.stderr
    assert json.loads(_run(tmp_path, "status").stdout)["servers"][0]["open_allocations"] == 0


def test_cli_rejections_exit_nonzero_with_reason(tmp_path):
    out = _run(tmp_path, "register", stdin=json.dumps({"name": "x", "kind": "warp-drive"}))
    assert out.returncode != 0
    assert "kind" in out.stderr

    out = _run(tmp_path, "allocate", "--server", "ghost", "--pkg", "demo", "--exp", "P1")
    assert out.returncode != 0


def test_cli_writes_only_under_resources_root(tmp_path):
    server = {"name": "local", "kind": "local", "gpus": [{"type": "a6000", "count": 1}]}
    _run(tmp_path, "register", stdin=json.dumps(server))
    _run(tmp_path, "allocate", "--server", "local", "--pkg", "demo", "--exp", "P1")

    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert written <= {
        "_resources/servers.json",
        "_resources/allocations.jsonl",
    }
