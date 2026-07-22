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


def test_event_store_commit_callers_are_owned_gateways():
    """Only semantic gateways, migration, and parity fixtures may commit."""
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
            (
                "lib/research_state/kernel.py",
                "commit_transaction",
                "commit",
            ): 1,
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


def test_low_level_json_writers_stay_inside_owned_modules():
    """Guard mutation ownership without freezing incidental call counts."""
    actual = _select(_production_calls(), LOW_LEVEL_WRITERS)
    owners = {
        "lib/research_state/store.py": {
            "EventStore.initialize",
            "EventStore.import_legacy_audit",
            "EventStore.write_note",
            "EventStore._audit",
            "EventStore._sync_audit_export",
            "EventStore._sync_commit_exports",
            "EventStore._sync_compatibility_exports",
        },
        "lib/research_state/paths.py": {
            "ResearchPaths.initialize",
            "ResearchPaths.finalize_migration",
        },
        "lib/research_state/migration.py": {
            "_copy_terminal_run",
            "_write_migration_manifest",
        },
        "lib/experiments/extract.py": {"extract_result"},
        "lib/experiments/harvest.py": {
            "RunState.write_status",
            "_callback_error",
            "run_command",
        },
        "lib/experiments/launch.py": {
            "_launch_failure_artifacts",
            "prepare_run",
        },
        "lib/resource_alloc/probe.py": {"_write_snapshot"},
        "lib/interface/serve.py": {
            "_command_serve",
            "_command_ensure",
            "_command_stop",
        },
    }
    unexpected = {
        call: count
        for call, count in actual.items()
        if call[0] not in owners or call[1] not in owners[call[0]]
    }
    assert not unexpected, f"unowned low-level writer(s): {unexpected}"
