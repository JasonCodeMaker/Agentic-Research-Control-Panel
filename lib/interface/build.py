"""Atomically rebuild the human interface from authoritative research data."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

from lib.research_state import EventStore, ResearchPaths, UpgradeRequired
from lib.self_evolve.dashboard import build_projection as self_evolution_projection

from .package import package_view_models, read_note_text, render_package_pages
from .project import (
    acknowledged_run_ids,
    brainstorm_detail_path,
    brainstorm_pages,
    brainstorm_views,
    live_run_views,
    render_global,
    render_jsonl,
    render_project_js,
    render_schema_js,
    render_scope_schema_js,
    rule_views,
    scope_projection,
    universal_rule_rows,
)


PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_SKILL = PIPELINE_ROOT / "skills" / "research-dashboard"
DASHBOARD_BUNDLE = DASHBOARD_SKILL / "assets" / "dashboard"
PACKAGE_TEMPLATES = PIPELINE_ROOT / "skills" / "research-package" / "templates"
RULE_FILES = ("html-rules.html", "trustworthy-research-rules.html")

@dataclass(frozen=True)
class BuildResult:
    """A completed immutable snapshot of one interface rebuild."""

    root: Path
    source_seq: int
    source_hash: str
    files: tuple[Path, ...]


def _write_text(root: Path, relative: str, text: str) -> Path:
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    return destination


def _write_json(root: Path, relative: str, value: Any) -> Path:
    return _write_text(
        root,
        relative,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _rewrite_static_asset(relative: Path, text: str) -> str:
    """Normalize path text in imported legacy NoteRefs only.

    Bundled assets are already canonical.  Keeping this idempotent adapter
    allows migrated HTML notes to render without becoming an authority source.
    """
    text = text.replace(
        "python research_html/scripts/serve_dashboard.py ensure --json",
        "python -m lib.interface.serve --workspace . ensure --json",
    )
    text = text.replace(
        "http://127.0.0.1:8904/research_html/live.html",
        "http://127.0.0.1:8904/live.html",
    )
    text = text.replace("/research_html/scope.html", "/scope.html")

    text = text.replace(
        "../outputs/_scope/transitions.jsonl", "data/scope-transitions.jsonl"
    )
    text = text.replace(
        "../outputs/_scope/triage.jsonl", "data/scope-triage.jsonl"
    )
    text = text.replace(
        "outputs/_scope/transitions.jsonl",
        ".research/state/events.jsonl (projected scope transitions)",
    )
    text = text.replace(
        "outputs/_scope/triage.jsonl",
        ".research/state/events.jsonl (projected triage)",
    )
    text = text.replace(
        "../outputs/_live/runs.jsonl", "data/live-runs.jsonl"
    )
    text = text.replace(
        "../outputs/_live/acknowledged.json", "data/live-acknowledged.json"
    )
    text = text.replace(
        "outputs/_live/runs.jsonl", ".research/state run aggregates"
    )
    text = text.replace(
        "python -m http.server",
        "python -m lib.interface.serve --workspace . ensure",
    )

    if relative.as_posix() == "scope.html":
        text = text.replace(
            "<code>data/scope-transitions.jsonl</code> directly in the browser, so",
            "<code>data/scope-transitions.jsonl</code> in the browser, so",
        )
        text = text.replace(
            "<code>.research/state/events.jsonl (projected scope transitions)</code> directly in the browser, so",
            "<code>data/scope-transitions.jsonl</code> in the browser, so",
        )
        text = text.replace(
            "proposals stay current without regenerating any dashboard data file.",
            "proposals stay current after each read-only interface projection rebuild.",
        )
        text = text.replace(
            "Source of truth: <code>.research/state/events.jsonl "
            "(projected scope transitions)</code> and\n"
            "      <code>.research/state/events.jsonl (projected triage)</code>, "
            "read directly.",
            "Source projections: <code>data/scope-transitions.jsonl</code> and\n"
            "      <code>data/scope-triage.jsonl</code>, generated from "
            ".research/state/events.jsonl.",
        )

    # Filesystem path text is the only broad migration expected-diff class.
    text = text.replace("/research_html/", "/")
    text = text.replace("research_html/", ".research/interface/")
    text = text.replace("outputs/", ".research/experiments/")
    return text


def _copy_static_bundle(stage: Path, bundle: Path) -> list[Path]:
    if not bundle.is_dir():
        raise FileNotFoundError(f"missing dashboard bundle: {bundle}")
    written: list[Path] = []
    for source in sorted(path for path in bundle.rglob("*") if path.is_file()):
        relative = source.relative_to(bundle)
        if "scripts" in relative.parts or "__pycache__" in relative.parts:
            continue
        if relative.parts[0] == "data":
            continue
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in {".html", ".js", ".css"}:
            text = source.read_text(encoding="utf-8")
            destination.write_text(
                _rewrite_static_asset(relative, text),
                encoding="utf-8",
            )
        else:
            shutil.copyfile(source, destination)
        written.append(destination)
    return written


def _copy_rules(stage: Path, skill_root: Path) -> tuple[list[Path], dict[str, str]]:
    written: list[Path] = []
    sources: dict[str, str] = {}
    for name in RULE_FILES:
        source = skill_root / "assets" / name
        if not source.is_file():
            raise FileNotFoundError(f"missing dashboard rule source: {source}")
        text = _rewrite_static_asset(Path("rules") / name, source.read_text(encoding="utf-8"))
        destination = _write_text(stage, f"rules/{name}", text)
        written.append(destination)
        sources[name] = text
    return written, sources


def _write_project_data(
    stage: Path,
    state: Mapping[str, Any],
    packages: list[dict[str, Any]],
    brainstorms: list[dict[str, Any]],
    rule_sources: Mapping[str, str],
    self_evolution: Mapping[str, Any],
) -> list[Path]:
    scope = scope_projection(state)
    rules = rule_views(state, bundled=universal_rule_rows(rule_sources))
    live_runs = live_run_views(state)
    files = [
        _write_text(stage, "data/schema.js", render_schema_js()),
        _write_text(stage, "data/scope-schema.js", render_scope_schema_js()),
        _write_text(stage, "data/research-packages.js", render_project_js(state, packages)),
        _write_text(stage, "data/brainstorms.js", render_global("BRAINSTORMS", brainstorms)),
        _write_text(stage, "data/rules.js", render_global("RESEARCH_RULES", rules)),
        _write_json(stage, "data/scope-projection.json", scope.nodes),
        _write_text(
            stage,
            "data/scope-projection.js",
            render_global("RESEARCH_SCOPE_PROJECTION", scope.nodes),
        ),
        _write_text(
            stage,
            "data/scope-transitions.jsonl",
            render_jsonl(scope.transitions),
        ),
        _write_text(stage, "data/scope-triage.jsonl", render_jsonl(scope.triage)),
        _write_text(stage, "data/live-runs.jsonl", render_jsonl(live_runs)),
        _write_json(
            stage,
            "data/live-acknowledged.json",
            {"run_ids": acknowledged_run_ids(state)},
        ),
        _write_json(stage, "data/self-evolution.json", self_evolution),
        _write_text(
            stage,
            "data/self-evolution.js",
            render_global("RESEARCH_SELF_EVOLUTION", self_evolution),
        ),
    ]
    return files


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_replace_tree(stage: Path, destination: Path) -> None:
    backup = destination.parent / f".interface-backup-{uuid.uuid4().hex}"
    had_destination = os.path.lexists(destination)
    try:
        if had_destination:
            os.replace(destination, backup)
        os.replace(stage, destination)
        _fsync_directory(destination.parent)
    except BaseException:
        if os.path.lexists(destination):
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        if os.path.lexists(backup):
            os.replace(backup, destination)
        raise
    else:
        if os.path.lexists(backup):
            if backup.is_dir() and not backup.is_symlink():
                shutil.rmtree(backup)
            else:
                backup.unlink()


@contextmanager
def _interface_projection_lock(paths: ResearchPaths) -> Iterator[None]:
    """Serialize whole interface snapshots for one workspace.

    The lock lives in the workspace-specific runtime directory, outside both
    authority and projection trees.  It must be acquired before reading state:
    locking only the final rename would still let a slow, stale renderer
    overwrite a newer projection.
    """
    paths.runtime.mkdir(parents=True, exist_ok=True)
    lock_path = paths.runtime / "interface-projection.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _build_interface_unlocked(
    paths: ResearchPaths,
    *,
    bundle: Path = DASHBOARD_BUNDLE,
    package_templates: Path = PACKAGE_TEMPLATES,
    allow_unversioned_migration: bool = False,
) -> BuildResult:
    """Build a complete projection and swap it into place in one rename step."""
    unversioned = paths.load_version() is None
    if unversioned and not allow_unversioned_migration:
        raise UpgradeRequired(
            f"upgrade-required: {paths.version_file} is missing; initialize a new "
            "workspace or run research-init before building the interface"
        )
    # This escape hatch is deliberately explicit and read-only.  It exists
    # solely so the migration command can prove that the interface is
    # rebuildable before VERSION publishes the staged state.
    state = EventStore(paths, migration_mode=unversioned).state()
    packages = package_view_models(state)
    brainstorms = brainstorm_views(state)
    self_evolution = self_evolution_projection(
        paths,
        skill_root=paths.workspace / ".agents" / "self-evolve",
        state_snapshot=state,
    )
    paths.root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".interface-build-", dir=paths.root))
    try:
        _copy_static_bundle(stage, bundle)
        _, rule_sources = _copy_rules(stage, DASHBOARD_SKILL)
        _write_project_data(
            stage,
            state,
            packages,
            brainstorms,
            rule_sources,
            self_evolution,
        )
        for record in brainstorms:
            relative = brainstorm_detail_path(record)
            detail_note = record.get("detail_note")
            if detail_note is not None and not isinstance(detail_note, Mapping):
                raise ValueError(
                    f"brainstorm {record.get('id')!r} has malformed detail_note"
                )
            if isinstance(detail_note, Mapping):
                # Compatibility path for migrated, self-contained legacy pages.
                text = read_note_text(paths, detail_note)
            else:
                document_note = record.get("document_note")
                if document_note is not None and not isinstance(document_note, Mapping):
                    raise ValueError(
                        f"brainstorm {record.get('id')!r} has malformed document_note"
                    )
                document_html = None
                if isinstance(document_note, Mapping):
                    mime = str(document_note.get("mime") or "")
                    if not mime.startswith("text/html"):
                        raise ValueError(
                            f"brainstorm {record.get('id')!r} document_note must be text/html"
                        )
                    document_html = read_note_text(paths, document_note)
                text = next(
                    iter(
                        brainstorm_pages(
                            [record],
                            document_html_by_id=(
                                {str(record.get("id") or ""): document_html}
                                if document_html is not None
                                else None
                            ),
                        ).values()
                    )
                )
            text = _rewrite_static_asset(Path(relative), text)
            _write_text(stage, relative, text)
        for package in packages:
            render_package_pages(
                paths=paths,
                package=package,
                templates_dir=package_templates,
                output_root=stage / "packages",
            )
        if (stage / "scripts").exists():
            raise ValueError("interface projection must not contain a scripts directory")
        if any(path.suffix == ".py" for path in stage.rglob("*") if path.is_file()):
            raise ValueError("interface projection must not contain Python entrypoints")
        _atomic_replace_tree(stage, paths.interface)
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage)
        raise

    files = tuple(
        sorted(path for path in paths.interface.rglob("*") if path.is_file())
    )
    return BuildResult(
        root=paths.interface,
        source_seq=int(state.get("source_seq") or 0),
        source_hash=str(state.get("source_hash") or ""),
        files=files,
    )


def build_interface(
    paths: ResearchPaths,
    *,
    bundle: Path = DASHBOARD_BUNDLE,
    package_templates: Path = PACKAGE_TEMPLATES,
    allow_unversioned_migration: bool = False,
) -> BuildResult:
    """Build and publish the latest complete interface projection."""
    with _interface_projection_lock(paths):
        return _build_interface_unlocked(
            paths,
            bundle=bundle,
            package_templates=package_templates,
            allow_unversioned_migration=allow_unversioned_migration,
        )
