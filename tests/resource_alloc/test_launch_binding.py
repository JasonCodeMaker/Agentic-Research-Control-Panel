import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.exp_live import launch  # noqa: E402


def _launch(tmp_path, **over):
    kwargs = dict(
        pkg="pkg-a", exp_id="P1", tmux_session="t-p1",
        command=[sys.executable, "-c", "print('ok')"],
        outputs_root=tmp_path / "outputs", use_tmux=False,
    )
    kwargs.update(over)
    return launch.launch_run(**kwargs)


def test_meta_records_server_and_alloc_binding(tmp_path):
    result = _launch(tmp_path, server="bunya", alloc_id="a-123")
    meta = json.loads((result.run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["server"] == "bunya"
    assert meta["alloc_id"] == "a-123"


def test_meta_defaults_to_local_server_without_allocation(tmp_path):
    result = _launch(tmp_path)
    meta = json.loads((result.run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["server"] == "local"
    assert meta["alloc_id"] is None
