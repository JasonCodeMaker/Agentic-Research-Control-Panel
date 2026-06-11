import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

from fact_transaction import FactTransaction


def _fact_temps(root: Path) -> list[Path]:
    return sorted(root.rglob("*.facttmp"))


def test_staged_writes_do_not_touch_live_files_until_commit(tmp_path):
    text_path = tmp_path / "facts" / "index.json"
    bytes_path = tmp_path / "facts" / "blob.bin"
    text_path.parent.mkdir()
    text_path.write_text("old fact\n", encoding="utf-8")

    tx = FactTransaction()
    tx.stage_text(text_path, "new fact\n")
    tx.stage_bytes(bytes_path, b"\x00\x01")

    assert text_path.read_text(encoding="utf-8") == "old fact\n"
    assert not bytes_path.exists()
    assert len(_fact_temps(tmp_path)) == 2

    tx.commit()

    assert text_path.read_text(encoding="utf-8") == "new fact\n"
    assert bytes_path.read_bytes() == b"\x00\x01"
    assert _fact_temps(tmp_path) == []


def test_commit_uses_os_replace_for_staged_files(tmp_path, monkeypatch):
    first = tmp_path / "facts" / "first.txt"
    second = tmp_path / "facts" / "second.txt"
    first.parent.mkdir()
    first.write_text("old first", encoding="utf-8")
    second.write_text("old second", encoding="utf-8")
    real_replace = os.replace
    replaced = []

    def recording_replace(src, dst):
        replaced.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr("fact_transaction.os.replace", recording_replace)

    tx = FactTransaction()
    tx.stage_text(first, "new first")
    tx.stage_text(second, "new second")
    tx.commit()

    final_dests = {dst for _, dst in replaced}
    assert first in final_dests
    assert second in final_dests
    assert first.read_text(encoding="utf-8") == "new first"
    assert second.read_text(encoding="utf-8") == "new second"


def test_validation_failure_before_commit_leaves_live_files_unchanged(tmp_path):
    first = tmp_path / "facts" / "first.txt"
    second = tmp_path / "facts" / "second.txt"
    first.parent.mkdir()
    first.write_text("old first", encoding="utf-8")
    second.write_text("old second", encoding="utf-8")

    tx = FactTransaction()
    tx.stage_text(first, "new first")
    tx.stage_text(second, "new second")
    _fact_temps(tmp_path)[0].unlink()

    with pytest.raises(FileNotFoundError):
        tx.commit()

    assert first.read_text(encoding="utf-8") == "old first"
    assert second.read_text(encoding="utf-8") == "old second"


def test_replace_error_rolls_back_live_files_and_removes_temp_files(tmp_path, monkeypatch):
    first = tmp_path / "facts" / "first.txt"
    second = tmp_path / "facts" / "second.txt"
    first.parent.mkdir()
    first.write_text("old first", encoding="utf-8")
    second.write_text("old second", encoding="utf-8")
    real_replace = os.replace

    def fail_second_final_replace(src, dst):
        if Path(dst) == second and Path(src).name.endswith(".facttmp") and "backup" not in Path(src).name:
            raise OSError("simulated replace failure")
        return real_replace(src, dst)

    monkeypatch.setattr("fact_transaction.os.replace", fail_second_final_replace)

    tx = FactTransaction()
    tx.stage_text(first, "new first")
    tx.stage_text(second, "new second")

    with pytest.raises(OSError, match="simulated replace failure"):
        tx.commit()

    assert first.read_text(encoding="utf-8") == "old first"
    assert second.read_text(encoding="utf-8") == "old second"
    assert _fact_temps(tmp_path) == []
