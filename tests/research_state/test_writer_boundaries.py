"""Static ownership contracts for management and telemetry writers."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROOTS = (ROOT / "lib", ROOT / "skills")
LOW_LEVEL_WRITERS = {
    "append_jsonl_fsync",
    "write_bytes_atomic",
    "write_json_atomic",
}


class _CallCollector(ast.NodeVisitor):
    def __init__(self, relative_path: str):
        self.relative_path = relative_path
        self.scope: list[str] = []
        self.calls: list[tuple[str, str, str]] = []
        self.attribute_calls: list[tuple[str, str, str, str]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        else:
            name = ""
        if name:
            self.calls.append(
                (
                    self.relative_path,
                    ".".join(self.scope) or "<module>",
                    name,
                )
            )
            if isinstance(node.func, ast.Attribute):
                self.attribute_calls.append(
                    (
                        self.relative_path,
                        ".".join(self.scope) or "<module>",
                        name,
                        ast.unparse(node.func.value),
                    )
                )
        self.generic_visit(node)


def _production_calls() -> Counter[tuple[str, str, str]]:
    calls: Counter[tuple[str, str, str]] = Counter()
    for production_root in PRODUCTION_ROOTS:
        for path in sorted(production_root.rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            collector = _CallCollector(relative)
            collector.visit(tree)
            calls.update(collector.calls)
    return calls


def _production_attribute_calls(
    name: str,
) -> Counter[tuple[str, str, str, str]]:
    calls: Counter[tuple[str, str, str, str]] = Counter()
    for production_root in PRODUCTION_ROOTS:
        for path in sorted(production_root.rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            collector = _CallCollector(relative)
            collector.visit(tree)
            calls.update(
                call for call in collector.attribute_calls if call[2] == name
            )
    return calls


def _select(
    calls: Counter[tuple[str, str, str]],
    names: set[str],
) -> Counter[tuple[str, str, str]]:
    return Counter(
        {
            call: count
            for call, count in calls.items()
            if call[2] in names
        }
    )


def _assert_allowlist(
    actual: Counter[tuple[str, ...]],
    expected: Counter[tuple[str, ...]],
) -> None:
    unexpected = actual - expected
    missing = expected - actual
    assert not unexpected and not missing, (
        f"writer boundary changed; unexpected={dict(unexpected)}, "
        f"missing={dict(missing)}"
    )


def test_event_store_commit_callers_are_explicitly_allowlisted():
    """Only the gateway, migration adapter, and temp parity fixture may commit."""
    actual = _select(_production_calls(), {"commit"})
    expected = Counter(
        {
            (
                "skills/research-op/scripts/management.py",
                "_commit",
                "commit",
            ): 1,
            (
                "lib/research_state/migration.py",
                "_commit_legacy",
                "commit",
            ): 1,
            (
                "lib/interface/parity.py",
                "_seed_fixture",
                "commit",
            ): 5,
        }
    )
    _assert_allowlist(actual, expected)


def test_rejection_audit_writer_is_owned_by_management_gateway():
    actual = _production_attribute_calls("record_rejected_attempt")
    expected = Counter(
        {
            (
                "skills/research-op/scripts/management.py",
                "record_rejected_attempt",
                "record_rejected_attempt",
                "EventStore(paths)",
            ): 1,
            (
                "lib/resource_alloc/__init__.py",
                "audit_rejection",
                "record_rejected_attempt",
                "research_management",
            ): 1,
            (
                "skills/research-op/scripts/research_op.py",
                "_error",
                "record_rejected_attempt",
                "management",
            ): 1,
        }
    )
    _assert_allowlist(actual, expected)


def test_low_level_json_writers_are_explicitly_allowlisted():
    """New state/run/runtime writers require an ownership review."""
    actual = _select(_production_calls(), LOW_LEVEL_WRITERS)
    expected = Counter(
        {
            # Management store owner.
            (
                "lib/research_state/store.py",
                "EventStore.initialize",
                "write_json_atomic",
            ): 1,
            (
                "lib/research_state/store.py",
                "EventStore.commit",
                "append_jsonl_fsync",
            ): 1,
            (
                "lib/research_state/store.py",
                "EventStore.commit",
                "write_json_atomic",
            ): 1,
            (
                "lib/research_state/store.py",
                "EventStore.write_note",
                "write_bytes_atomic",
            ): 1,
            (
                "lib/research_state/store.py",
                "EventStore.import_legacy_audit",
                "append_jsonl_fsync",
            ): 1,
            (
                "lib/research_state/store.py",
                "EventStore.recover",
                "write_json_atomic",
            ): 1,
            (
                "lib/research_state/store.py",
                "EventStore._audit",
                "append_jsonl_fsync",
            ): 1,
            # Version owner and explicit migration adapter.
            (
                "lib/research_state/paths.py",
                "ResearchPaths.initialize",
                "write_bytes_atomic",
            ): 1,
            (
                "lib/research_state/paths.py",
                "ResearchPaths.finalize_migration",
                "write_bytes_atomic",
            ): 1,
            (
                "lib/research_state/migration.py",
                "_copy_terminal_run",
                "write_json_atomic",
            ): 1,
            (
                "lib/research_state/migration.py",
                "_write_migration_manifest",
                "write_json_atomic",
            ): 1,
            # Run-owned telemetry.
            ("lib/experiments/extract.py", "extract_result", "write_json_atomic"): 1,
            (
                "lib/experiments/harvest.py",
                "RunState.write_status",
                "write_json_atomic",
            ): 1,
            (
                "lib/experiments/harvest.py",
                "_callback_error",
                "append_jsonl_fsync",
            ): 1,
            ("lib/experiments/harvest.py", "run_command", "write_json_atomic"): 2,
            ("lib/experiments/harvest.py", "run_command", "append_jsonl_fsync"): 2,
            (
                "lib/experiments/launch.py",
                "_launch_failure_artifacts",
                "write_json_atomic",
            ): 2,
            ("lib/experiments/launch.py", "prepare_run", "write_json_atomic"): 1,
            (
                "skills/research-run/scripts/skeleton.py",
                "experiment",
                "write_json_atomic",
            ): 5,
            (
                "skills/research-run/scripts/skeleton.py",
                "experiment",
                "append_jsonl_fsync",
            ): 2,
            # XDG runtime caches, outside persistent research state.
            (
                "lib/resource_alloc/probe.py",
                "_write_snapshot",
                "write_json_atomic",
            ): 1,
            (
                "lib/interface/serve.py",
                "_command_serve",
                "write_json_atomic",
            ): 1,
            (
                "lib/interface/serve.py",
                "_command_ensure",
                "write_json_atomic",
            ): 1,
            (
                "lib/interface/serve.py",
                "_command_stop",
                "write_json_atomic",
            ): 1,
        }
    )
    _assert_allowlist(actual, expected)
