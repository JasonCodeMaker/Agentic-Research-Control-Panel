"""Stage fact/projection file writes and publish them as one transaction."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _StagedWrite:
    dest: Path
    temp: Path


@dataclass
class _CommitRecord:
    dest: Path
    temp: Path
    backup: Path | None
    installed: bool = False


class FactTransaction:
    """Stage file contents under destination directories, then atomically publish."""

    def __init__(self) -> None:
        self._staged: list[_StagedWrite] = []
        self._cleanup_paths: list[Path] = []

    def stage_text(self, path: Path, text: str) -> None:
        dest = Path(path)
        temp = self._new_temp_path(dest)
        temp.write_text(text, encoding="utf-8")
        self._staged.append(_StagedWrite(dest=dest, temp=temp))
        self._cleanup_paths.append(temp)

    def stage_bytes(self, path: Path, data: bytes) -> None:
        dest = Path(path)
        temp = self._new_temp_path(dest)
        temp.write_bytes(data)
        self._staged.append(_StagedWrite(dest=dest, temp=temp))
        self._cleanup_paths.append(temp)

    def commit(self) -> None:
        records: list[_CommitRecord] = []
        try:
            self._validate()
            for staged in self._staged:
                backup = None
                if staged.dest.exists():
                    backup = self._new_temp_path(staged.dest, role="backup")
                    self._cleanup_paths.append(backup)
                    os.replace(staged.dest, backup)
                records.append(_CommitRecord(dest=staged.dest, temp=staged.temp, backup=backup))

            for record in records:
                os.replace(record.temp, record.dest)
                record.installed = True
        except Exception:
            self._rollback(records)
            self.cleanup()
            raise

        self.cleanup()

    def cleanup(self) -> None:
        for path in reversed(self._cleanup_paths):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        self._cleanup_paths.clear()
        self._staged.clear()

    def _validate(self) -> None:
        seen: set[Path] = set()
        for staged in self._staged:
            if staged.dest in seen:
                raise ValueError(f"duplicate staged path: {staged.dest}")
            seen.add(staged.dest)
            if not staged.temp.exists():
                raise FileNotFoundError(staged.temp)
            if not staged.dest.parent.exists():
                raise FileNotFoundError(staged.dest.parent)
            if not staged.dest.parent.is_dir():
                raise NotADirectoryError(staged.dest.parent)
            if staged.dest.exists() and staged.dest.is_dir():
                raise IsADirectoryError(staged.dest)

    def _rollback(self, records: list[_CommitRecord]) -> None:
        for record in reversed(records):
            if record.installed:
                try:
                    record.dest.unlink()
                except FileNotFoundError:
                    pass
            if record.backup and record.backup.exists():
                os.replace(record.backup, record.dest)

    def _new_temp_path(self, dest: Path, *, role: str = "stage") -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(
            prefix=f".{dest.name}.{role}.",
            suffix=".facttmp",
            dir=dest.parent,
        )
        os.close(fd)
        temp = Path(name)
        temp.unlink()
        return temp
