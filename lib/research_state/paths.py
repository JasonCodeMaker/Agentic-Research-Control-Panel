"""One resolver for every Trustworthy-managed workspace path."""

from __future__ import annotations

import hashlib
import fcntl
import os
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .io import write_bytes_atomic


CURRENT_VERSION = 1
VERSION_FILENAME = "VERSION"
LEGACY_MARKERS = ("research_html", "outputs")


class UpgradeRequired(RuntimeError):
    """The managed root is absent, unversioned, or unsupported."""


class UnsupportedResearchVersion(RuntimeError):
    """The workspace version is unknown to this installation."""


def _absolute(workspace: Path, value: str | os.PathLike[str]) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (workspace / path).resolve()


@dataclass(frozen=True)
class ResearchPaths:
    """Resolved paths below one workspace-local research root."""

    workspace: Path
    root: Path

    @classmethod
    def resolve(
        cls,
        *,
        workspace: str | os.PathLike[str] | None = None,
        research_root: str | os.PathLike[str] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "ResearchPaths":
        workspace_path = Path(workspace or Path.cwd()).expanduser().resolve()
        env = os.environ if environ is None else environ
        selected: str | os.PathLike[str]
        if research_root is not None:
            selected = research_root
        elif env.get("RESEARCH_ROOT"):
            selected = env["RESEARCH_ROOT"]
        elif env.get("RESEARCH_RUNTIME_ROOT"):
            warnings.warn(
                "RESEARCH_RUNTIME_ROOT is deprecated; use RESEARCH_ROOT",
                DeprecationWarning,
                stacklevel=2,
            )
            selected = env["RESEARCH_RUNTIME_ROOT"]
        else:
            selected = ".research"
        return cls(workspace=workspace_path, root=_absolute(workspace_path, selected))

    @property
    def version_file(self) -> Path:
        return self.root / VERSION_FILENAME

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def events(self) -> Path:
        return self.state / "events.jsonl"

    @property
    def current(self) -> Path:
        return self.state / "current.json"

    @property
    def database(self) -> Path:
        """Transactional authority for management state and command receipts."""
        return self.state / "research.sqlite3"

    @property
    def state_lock(self) -> Path:
        return self.state / ".lock"

    @property
    def notes(self) -> Path:
        return self.state / "notes"

    @property
    def audit(self) -> Path:
        return self.root / "audit"

    @property
    def audit_actions(self) -> Path:
        return self.audit / "actions.jsonl"

    @property
    def experiments(self) -> Path:
        return self.root / "experiments"

    @property
    def interface(self) -> Path:
        return self.root / "interface"

    @property
    def interface_data(self) -> Path:
        return self.interface / "data"

    @property
    def interface_packages(self) -> Path:
        return self.interface / "packages"

    @property
    def runtime(self) -> Path:
        base = os.environ.get("XDG_RUNTIME_DIR")
        runtime_base = Path(base) if base else Path(tempfile.gettempdir()) / f"research-{os.getuid()}"
        # The authority root, not the source workspace, is the concurrency
        # identity. Two callers may intentionally point different workspaces
        # at the same absolute --research-root and must then share runtime
        # locks, server metadata, and resource snapshots.
        digest = hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()[:16]
        return runtime_base / "trustworthy-research" / digest

    @property
    def dashboard_server_state(self) -> Path:
        return self.runtime / "dashboard_server.json"

    def note(self, sha256: str) -> Path:
        digest = sha256.removeprefix("sha256:")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
            raise ValueError("note sha256 must be a 64-character hexadecimal digest")
        return self.notes / f"{digest.lower()}.md"

    def experiment_dir(self, package_id: str, experiment_id: str) -> Path:
        self._validate_id(package_id)
        self._validate_id(experiment_id)
        return self.experiments / package_id / experiment_id

    def run_dir(self, package_id: str, experiment_id: str, run_id: str) -> Path:
        self._validate_id(run_id)
        return self.experiment_dir(package_id, experiment_id) / run_id

    def package_interface(self, slug: str) -> Path:
        self._validate_id(slug)
        return self.interface_packages / slug

    def load_version(self) -> int | None:
        if not self.version_file.exists():
            return None
        raw = self.version_file.read_text(encoding="utf-8").strip()
        try:
            version = int(raw)
        except ValueError as exc:
            raise UnsupportedResearchVersion(f"invalid {self.version_file}: {raw!r}") from exc
        if version != CURRENT_VERSION:
            raise UnsupportedResearchVersion(
                f"workspace version {version} is unsupported; expected {CURRENT_VERSION}"
            )
        return version

    def legacy_markers(self) -> list[Path]:
        return [self.workspace / name for name in LEGACY_MARKERS if (self.workspace / name).exists()]

    def _create_layout(self) -> list[Path]:
        created: list[Path] = []
        for directory in (
            self.state,
            self.notes,
            self.audit,
            self.experiments,
            self.interface,
        ):
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                created.append(directory)
        return created

    def initialize(self) -> list[Path]:
        """Create a versioned empty layout without adopting legacy data."""
        markers = self.legacy_markers()
        if markers and not self.version_file.exists():
            raise UpgradeRequired(
                "upgrade-required: existing unversioned research data found at "
                + ", ".join(str(path) for path in markers)
                + "; automatic migration is no longer supported"
            )

        self.root.mkdir(parents=True, exist_ok=True)
        directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_EX)
            existing_version = self.load_version()
            if existing_version is None:
                root_has_content = any(self.root.iterdir())
                if root_has_content:
                    raise UpgradeRequired(
                        "upgrade-required: existing unversioned research data found at "
                        + str(self.root)
                        + "; automatic migration is no longer supported"
                    )
            created = self._create_layout()
            if existing_version is None:
                write_bytes_atomic(
                    self.version_file,
                    f"{CURRENT_VERSION}\n".encode("utf-8"),
                )
                created.append(self.version_file)
            return created
        finally:
            fcntl.flock(directory_fd, fcntl.LOCK_UN)
            os.close(directory_fd)

    @staticmethod
    def _validate_id(value: str) -> None:
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or "\x00" in value
        ):
            raise ValueError(f"unsafe research identifier: {value!r}")


def add_research_root_argument(parser) -> None:
    """Install the common CLI override without duplicating default-path logic."""
    parser.add_argument(
        "--research-root",
        help="Trustworthy data root (default: RESEARCH_ROOT or .research)",
    )
