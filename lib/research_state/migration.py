"""Explicit, idempotent migration from legacy workspace stores into shadow state."""

from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from .io import (
    canonical_json,
    read_json,
    read_jsonl,
    write_json_atomic,
)
from .paths import CURRENT_VERSION, ResearchPaths
from .policy import from_legacy
from .schema import compatibility_map, enum
from .store import EventStore, management_lock


LEGACY_INTERFACE = "research_html"
LEGACY_OUTPUTS = "outputs"
ACTOR = {"type": "system", "id": "research-migrate"}
TERMINAL_RUN_STATUSES = {"COMPLETED", "FAILED", "HALTED", "SKIPPED"}
ACTIVE_RUN_STATUSES = {"QUEUED", "RUNNING", "STALE"}
PACKAGE_SHADOW_OWNERS = {
    "methodsTried": "RunResultFinalized",
    "resultGateRows": "RunResultFinalized",
    "resultBlocks": "RunResultFinalized",
    "analysisInsights": "Learning",
    "implementationReviews": "Change",
    "acknowledgements": "Decision",
}
UNMEASURED_VALUES = {"", "-", "—", "missing", "none", "null", "pending", "unmeasured"}


class MigrationError(RuntimeError):
    """Legacy data is malformed or cannot be mapped without guessing."""


@dataclass(frozen=True)
class LegacyRecord:
    event_type: str
    aggregate_type: str
    aggregate_id: str
    record: dict[str, Any]
    source: str
    identity: str

    @property
    def digest(self) -> str:
        value = {
            "source": self.source,
            "identity": self.identity,
            "record": self.record,
            "event_type": self.event_type,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
        }
        return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "record": self.record,
            "_migration": {
                "source": self.source,
                "identity": self.identity,
                "sha256": self.digest,
            },
        }


@dataclass(frozen=True)
class LegacyRun:
    run_id: str
    package_id: str | None
    experiment_local_id: str | None
    canonical_experiment_id: str | None
    experiment_identity_error: str | None
    status: str
    source_dir: Path | None
    meta: dict[str, Any]
    status_record: dict[str, Any]
    history: tuple[dict[str, Any], ...]

    @property
    def experiment_id(self) -> str | None:
        return self.canonical_experiment_id

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES


@dataclass(frozen=True)
class SemanticFactAnalysis:
    """Typed migration records plus a row-level disposition ledger."""

    records: tuple[LegacyRecord, ...]
    ledger: tuple[dict[str, Any], ...]
    blockers: tuple[dict[str, Any], ...]

    def gate(self) -> dict[str, Any]:
        counts = {
            disposition: sum(
                row.get("disposition") == disposition for row in self.ledger
            )
            for disposition in ("canonicalized", "derivable", "unresolved")
        }
        return {
            "ok": not self.blockers,
            "status": "passed" if not self.blockers else "blocked",
            "counts": counts,
            "ledger": copy.deepcopy(list(self.ledger)),
            "unresolved": copy.deepcopy(list(self.blockers)),
        }


@dataclass(frozen=True)
class ExperimentIdentityIndex:
    """Resolve package-local legacy handles to one canonical Experiment id."""

    by_alias: dict[tuple[str, str], str]
    local_by_canonical: dict[tuple[str, str], str]

    def resolve(
        self,
        package_id: str,
        *references: Any,
    ) -> str | None:
        tokens = {
            str(reference)
            for reference in references
            if reference is not None and str(reference).strip()
        }
        if not tokens:
            return None
        unknown = sorted(
            token
            for token in tokens
            if (package_id, token) not in self.by_alias
        )
        if unknown:
            raise MigrationError(
                f"package {package_id} has no canonical Experiment for legacy "
                f"identifier(s): {unknown}"
            )
        resolved = {
            self.by_alias[(package_id, token)]
            for token in tokens
        }
        if len(resolved) != 1:
            raise MigrationError(
                f"package {package_id} has conflicting legacy Experiment "
                f"identifiers {sorted(tokens)} -> {sorted(resolved)}"
            )
        return next(iter(resolved))

    def local_id(self, package_id: str, experiment_id: str) -> str:
        try:
            return self.local_by_canonical[(package_id, experiment_id)]
        except KeyError as exc:
            raise MigrationError(
                f"canonical Experiment {experiment_id!r} has no package-local "
                f"identifier in {package_id}"
            ) from exc


def _experiment_identity_index(
    records: Iterable[LegacyRecord],
) -> ExperimentIdentityIndex:
    by_alias: dict[tuple[str, str], str] = {}
    local_by_canonical: dict[tuple[str, str], str] = {}
    for item in records:
        if item.aggregate_type != "experiment":
            continue
        package_id = item.record.get("package_id")
        local_id = item.record.get("local_id")
        if not isinstance(package_id, str) or not package_id:
            continue
        if not isinstance(local_id, str) or not local_id:
            # Scope could record a future package owner before the package
            # inventory assigned its legacy local handle. The later package
            # import supplies the resolvable alias; this snapshot alone cannot.
            continue
        canonical_id = str(item.aggregate_id)
        canonical_key = (package_id, canonical_id)
        existing_local = local_by_canonical.get(canonical_key)
        if existing_local not in {None, local_id}:
            raise MigrationError(
                f"canonical Experiment {canonical_id!r} has conflicting local "
                f"identifiers in {package_id}: {existing_local!r}, {local_id!r}"
            )
        local_by_canonical[canonical_key] = local_id
        aliases = {
            canonical_id,
            local_id,
            f"{package_id}::{local_id}",
            *(
                str(alias)
                for alias in item.record.get("aliases", [])
                if alias is not None and str(alias).strip()
            ),
        }
        for alias in aliases:
            key = (package_id, alias)
            existing = by_alias.get(key)
            if existing not in {None, canonical_id}:
                raise MigrationError(
                    f"legacy Experiment alias {alias!r} in {package_id} maps "
                    f"to both {existing!r} and {canonical_id!r}"
                )
            by_alias[key] = canonical_id
    return ExperimentIdentityIndex(by_alias, local_by_canonical)


def _relative(path: Path, workspace: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return read_jsonl(path)
    except (ValueError, json.JSONDecodeError) as exc:
        raise MigrationError(f"malformed JSONL store {path}: {exc}") from exc


def _json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MigrationError(f"malformed JSON store {path}: {exc}") from exc


def _one_value(
    *,
    label: str,
    run_id: str,
    values: Iterable[Any],
) -> str | None:
    candidates = {
        str(value)
        for value in values
        if value is not None and str(value).strip()
    }
    if len(candidates) > 1:
        raise MigrationError(
            f"legacy run {run_id} has conflicting {label}: {sorted(candidates)}"
        )
    return next(iter(candidates), None)


def _canonical_run_status(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return compatibility_map("run_status").get(raw, raw)


def _js_global(path: Path, name: str) -> Any:
    if not path.exists():
        return None
    script = r"""
const fs = require("fs");
const vm = require("vm");
const context = {window: {}};
context.globalThis = context;
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), context, {filename: process.argv[1]});
const value = context.window[process.argv[2]];
process.stdout.write(JSON.stringify(value === undefined ? null : value));
"""
    try:
        result = subprocess.run(
            ["node", "-e", script, str(path), name],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return json.loads(result.stdout)
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise MigrationError(f"cannot read {name} from {path}: {exc}") from exc


def _scope_record(
    record: dict[str, Any],
    source: str,
    index: int,
    *,
    direction_versions: dict[str, int] | None = None,
    transition_history: list[dict[str, Any]] | None = None,
) -> LegacyRecord:
    node = record.get("node")
    if not isinstance(node, dict):
        raise MigrationError(f"{source}:{index}: Scope transition has no node snapshot")
    level = node.get("level")
    aggregate_type = {"project": "project", "direction": "direction", "task": "experiment"}.get(level)
    if aggregate_type is None:
        raise MigrationError(f"{source}:{index}: unknown Scope level {level!r}")
    migrated = dict(node)
    if level == "task":
        spec = node.get("spec")
        if not isinstance(spec, dict):
            raise MigrationError(f"{source}:{index}: Task has no spec")
        direction_id = (node.get("parents") or [None])[0]
        if not isinstance(direction_id, str) or not direction_id:
            raise MigrationError(
                f"{source}:{index}: Task has no parent Direction"
            )
        direction_version = (direction_versions or {}).get(direction_id)
        if direction_version is None:
            raise MigrationError(
                f"{source}:{index}: Task references unknown Direction "
                f"{direction_id!r}"
            )
        purpose = spec.get("experiment") or spec.get("purpose")
        config_ref = spec.get("config") or spec.get("config_ref")
        gate = spec.get("gate")
        control_mode = spec.get("control_mode")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (purpose, config_ref, gate, control_mode)
        ):
            raise MigrationError(
                f"{source}:{index}: Task spec cannot form the canonical "
                "four-field Experiment.spec"
            )
        scope_status = str(node.get("status") or "ARCHIVED")
        if scope_status not in set(enum("scope_status")):
            scope_status = "ARCHIVED"
        migrated = {
            "id": node["id"],
            "direction_id": direction_id,
            "package_id": node.get("package_id"),
            "spec": {
                "purpose": purpose,
                "config_ref": config_ref,
                "gate": gate,
                "control_mode": control_mode,
            },
            "status": "PLANNED" if scope_status == "ACTIVE" else "BLOCKED",
            "scope_status": scope_status,
            "scope_confirmation": (
                "CONFIRMED" if scope_status == "ACTIVE" else "STALE"
            ),
            "scope_version": int(node.get("version") or 1),
            "scope_source": str(node.get("source") or source),
            "confirmed_direction_version": direction_version,
            "aliases": [node["id"]],
            "legacy_scope_kind": "task",
        }
    migrated["_legacy_transition"] = {
        key: record.get(key)
        for key in (
            "transaction_id",
            "scope_version",
            "op",
            "gate",
            "trigger",
            "cause",
            "invalidates",
            "reopens",
            "dial_revert",
        )
    }
    migrated["legacy_transitions"] = copy.deepcopy(
        transition_history
        if transition_history is not None
        else [record]
    )
    return LegacyRecord(
        event_type="AggregateImported",
        aggregate_type=aggregate_type,
        aggregate_id=str(node["id"]),
        record=migrated,
        source=source,
        identity=str(record.get("transaction_id") or index),
    )


def _proposal_record(record: dict[str, Any], source: str, index: int) -> LegacyRecord:
    item_id = record.get("id")
    if not item_id:
        raise MigrationError(f"{source}:{index}: Triage record has no id")
    status = str(record.get("status", "pending")).lower()
    event_type = {
        "pending": "ProposalSubmitted",
        "accepted": "ProposalAccepted",
        "rejected": "ProposalRejected",
    }.get(status)
    if event_type is None:
        raise MigrationError(f"{source}:{index}: unknown Triage status {status!r}")
    return LegacyRecord(
        event_type=event_type,
        aggregate_type="proposal",
        aggregate_id=str(item_id),
        record=dict(record),
        source=source,
        identity=f"{item_id}:{index}",
    )


def _experiment_record(
    package_id: str,
    raw: dict[str, Any],
    source: str,
    index: int,
    *,
    scope_experiments: dict[str, LegacyRecord],
    package_direction_id: str,
    package_direction_version: int,
) -> LegacyRecord:
    experiment_id = raw.get("id") or raw.get("expId") or raw.get("exp_id")
    if not experiment_id:
        raise MigrationError(f"{source}: package {package_id} experiment {index} has no id")
    status = raw.get("status", "pending")
    canonical_status = compatibility_map("experiment_status").get(str(status), status)
    local_id = str(experiment_id)
    source_scope_id = (
        raw.get("sourceTask")
        or raw.get("source_task")
        or raw.get("source_task_id")
    )
    scoped = None
    if source_scope_id is not None:
        scoped = scope_experiments.get(str(source_scope_id))
        if scoped is None:
            raise MigrationError(
                f"{source}: package {package_id} experiment {local_id} "
                f"references unknown sourceTask {source_scope_id!r}"
            )
    internal_id = str(
        scoped.aggregate_id
        if scoped is not None
        else raw.get("internal_id") or f"{package_id}::{local_id}"
    )
    aliases = [
        str(alias)
        for alias in [*(raw.get("aliases") or []), local_id]
        if str(alias)
    ]
    if scoped is not None:
        record = copy.deepcopy(scoped.record)
        for field in (
            "label",
            "output",
            "measures",
            "requiresCode",
            "complex",
            "resultSchemaRef",
            "resultSchema",
            "runLink",
            "docsAnchor",
        ):
            if field in raw:
                record[field] = copy.deepcopy(raw[field])
    else:
        record = {
            "direction_id": package_direction_id,
            "spec": {
                "purpose": str(
                    raw.get("purpose")
                    or raw.get("label")
                    or "unmeasured"
                ),
                "config_ref": str(
                    raw.get("config_ref") or raw.get("config") or ""
                ),
                "gate": str(raw.get("gate") or "unmeasured"),
                "control_mode": str(
                    raw.get("control_mode")
                    or raw.get("controlMode")
                    or "SUPERVISED"
                ),
            },
            "scope_status": "ARCHIVED",
            "scope_confirmation": "STALE",
            "scope_version": int(raw.get("scope_version") or 1),
            "scope_source": "legacy-package-inventory",
            "confirmed_direction_version": package_direction_version,
        }
    record.update(
        {
            "id": internal_id,
            "local_id": local_id,
            "package_id": package_id,
            "status": canonical_status,
            "aliases": list(
                dict.fromkeys([*(record.get("aliases") or []), *aliases])
            ),
        }
    )
    for legacy_field in ("sourceTask", "source_task", "source_task_id"):
        record.pop(legacy_field, None)
    record.pop("after", None)
    return LegacyRecord(
        event_type="AggregateImported",
        aggregate_type="experiment",
        aggregate_id=internal_id,
        record=record,
        source=source,
        identity=f"{package_id}:experiment:{local_id}",
    )


def _package_records(
    path: Path,
    workspace: Path,
    *,
    scope_experiments: dict[str, LegacyRecord],
    direction_versions: dict[str, int],
) -> Iterator[LegacyRecord]:
    packages = _js_global(path, "RESEARCH_PACKAGES")
    if packages is None:
        return
    if not isinstance(packages, list):
        raise MigrationError(f"{path}: RESEARCH_PACKAGES must be an array")
    source = _relative(path, workspace)
    for index, raw in enumerate(packages, start=1):
        if not isinstance(raw, dict) or not raw.get("id"):
            raise MigrationError(f"{source}: package row {index} has no id")
        package_id = str(raw["id"])
        category = str(raw.get("category"))
        status = str(raw.get("status"))
        orthogonal = from_legacy(category, status, raw)
        record = dict(raw)
        record.update(
            {
                "id": package_id,
                "slug": str(raw.get("slug") or package_id),
                **orthogonal,
                "category": category,
                "status": status,
            }
        )
        experiments = record.pop("experiments", [])
        if experiments is None:
            experiments = []
        if not isinstance(experiments, list):
            raise MigrationError(
                f"{source}: package {package_id} experiments must be an array"
            )
        source_scope_ids = [
            str(
                experiment.get("sourceTask")
                or experiment.get("source_task")
                or experiment.get("source_task_id")
            )
            for experiment in experiments
            if isinstance(experiment, dict)
            and (
                experiment.get("sourceTask")
                or experiment.get("source_task")
                or experiment.get("source_task_id")
            )
        ]
        mapped_directions = {
            str(scope_experiments[source_id].record.get("direction_id"))
            for source_id in source_scope_ids
            if source_id in scope_experiments
        }
        direction_id = str(
            raw.get("direction_id")
            or raw.get("sourceDirection")
            or (
                next(iter(mapped_directions))
                if len(mapped_directions) == 1
                else f"legacy-unscoped/{package_id}"
            )
        )
        direction_version = int(
            raw.get("sourceVersion")
            or direction_versions.get(direction_id)
            or 1
        )
        migrated_experiments: list[LegacyRecord] = []
        for exp_index, experiment in enumerate(experiments, start=1):
            if not isinstance(experiment, dict):
                raise MigrationError(
                    f"{source}: package {package_id} experiment {exp_index} "
                    "must be an object"
                )
            migrated_experiments.append(
                _experiment_record(
                    package_id,
                    experiment,
                    source,
                    exp_index,
                    scope_experiments=scope_experiments,
                    package_direction_id=direction_id,
                    package_direction_version=direction_version,
                )
            )
        record.update(
            {
                "direction_id": direction_id,
                "sourceDirection": direction_id,
                "sourceVersion": direction_version,
                "sourceChange": str(
                    raw.get("sourceChange") or f"legacy-import:{source}"
                ),
                "sourceExperiments": [
                    {
                        "id": item.aggregate_id,
                        "version": item.record["scope_version"],
                        "source": item.record["scope_source"],
                    }
                    for item in migrated_experiments
                ],
            }
        )
        yield LegacyRecord(
            event_type="AggregateImported",
            aggregate_type="package",
            aggregate_id=package_id,
            record=record,
            source=source,
            identity=f"package:{package_id}",
        )
        yield from migrated_experiments


def _global_records(
    path: Path,
    global_name: str,
    aggregate_type: str,
    workspace: Path,
) -> Iterator[LegacyRecord]:
    rows = _js_global(path, global_name)
    if rows is None:
        return
    if not isinstance(rows, list):
        raise MigrationError(f"{path}: {global_name} must be an array")
    source = _relative(path, workspace)
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise MigrationError(f"{source}:{index}: row must be an object")
        identity = row.get("id") or row.get("slug") or index
        target_type = (
            "learning"
            if aggregate_type == "rule" and row.get("kind") == "lesson"
            else aggregate_type
        )
        yield LegacyRecord(
            event_type="AggregateImported",
            aggregate_type=target_type,
            aggregate_id=str(identity),
            record=dict(row),
            source=source,
            identity=str(identity),
        )


def _knowledge_records(
    path: Path,
    aggregate_type: str,
    workspace: Path,
) -> Iterator[LegacyRecord]:
    source = _relative(path, workspace)
    for index, row in enumerate(_jsonl(path), start=1):
        if aggregate_type == "paper":
            identity = row.get("id") or row.get("arxiv") or row.get("source_id")
        elif aggregate_type == "knowledge_gap":
            identity = row.get("id")
        else:
            identity = hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()[:20]
        if not identity:
            raise MigrationError(f"{source}:{index}: knowledge row has no stable identity")
        yield LegacyRecord(
            event_type="AggregateImported",
            aggregate_type=aggregate_type,
            aggregate_id=str(identity),
            record=dict(row),
            source=source,
            identity=str(identity),
        )


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise MigrationError(f"cannot read legacy CSV store {path}: {exc}") from exc
    for index, row in enumerate(rows, start=2):
        if None in row:
            raise MigrationError(f"{path}:{index}: CSV row has surplus unnamed fields")
    return [{str(key): str(value or "") for key, value in row.items()} for row in rows]


def _package_facts_js(path: Path, package_id: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    marker = f"window.PACKAGE_FACTS[{json.dumps(package_id)}] = "
    if marker not in text:
        raise MigrationError(f"{path}: cannot find PACKAGE_FACTS[{package_id!r}]")
    raw = text.split(marker, 1)[1].strip()
    if raw.endswith(";"):
        raw = raw[:-1]
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MigrationError(f"{path}: malformed package facts: {exc}") from exc
    if not isinstance(value, dict):
        raise MigrationError(f"{path}: package facts must be an object")
    return value


def _legacy_fact_value(path: Path, package_id: str) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if path.name == f"{package_id}.facts.js":
        value: Any = _package_facts_js(path, package_id)
        kind = "package-facts"
    elif suffix == ".csv":
        value = _read_csv(path)
        kind = "csv"
    elif suffix == ".json":
        value = _json(path)
        kind = "json"
    elif suffix == ".jsonl":
        value = _jsonl(path)
        kind = "jsonl"
    else:
        raise MigrationError(f"unsupported package fact file: {path}")
    return {
        "format": kind,
        "sha256": _sha256_file(path),
        "data": value,
    }


def _package_fact_records(
    root: Path,
    workspace: Path,
    *,
    known_packages: set[str],
) -> Iterator[LegacyRecord]:
    """Lift every package-owned JS/CSV/JSON fact into package state."""
    if not root.exists():
        return
    by_package: dict[str, list[Path]] = {}
    for path in sorted(root.glob("*.facts.js")):
        by_package.setdefault(path.name.removesuffix(".facts.js"), []).append(path)
    for package_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        by_package.setdefault(package_dir.name, []).extend(
            path
            for path in sorted(package_dir.rglob("*"))
            if path.is_file() or path.is_symlink()
        )
    for package_id, files in sorted(by_package.items()):
        if package_id not in known_packages:
            yield LegacyRecord(
                "AggregateImported",
                "package",
                package_id,
                {
                    "id": package_id,
                    "slug": package_id,
                    "lifecycle": "ACTIVE",
                    "phase": None,
                    "blocker": {
                        "code": "LEGACY_PACKAGE_STATE_UNKNOWN",
                        "summary": "Package facts existed without an inventory record.",
                    },
                },
                _relative(root, workspace),
                f"facts-placeholder:{package_id}",
            )
            known_packages.add(package_id)
        for path in files:
            if path.is_symlink() or (
                path.name != f"{package_id}.facts.js"
                and path.suffix.lower() not in {".csv", ".json", ".jsonl"}
            ):
                # Inventory owns unsupported/symlink blockers. Discovery only
                # reads inputs that have a deterministic import rule.
                continue
            relative = (
                path.name
                if path.parent == root
                else path.relative_to(root / package_id).as_posix()
            )
            yield LegacyRecord(
                "AggregatePatched",
                "package",
                package_id,
                {
                    "legacy_fact_store": {
                        "role": "raw-provenance-archive",
                        "authoritative": False,
                        "files": {
                            relative: _legacy_fact_value(path, package_id),
                        }
                    }
                },
                _relative(path, workspace),
                f"package-fact:{package_id}:{relative}",
            )


def _semantic_source_sha(workspace: Path, source: str, fallback: str) -> str:
    path = workspace / source
    return _sha256_file(path) if path.is_file() else fallback


def _semantic_row_id(row: Any, index: int) -> str:
    if isinstance(row, dict):
        for field in ("row_id", "id", "change_id", "ack_type", "slug"):
            value = row.get(field)
            if value not in (None, ""):
                return str(value)
    return str(index)


def _semantic_ledger_row(
    *,
    source: str,
    source_sha256: str,
    package_id: str,
    fact_kind: str,
    row_id: str,
    row: Any,
    disposition: str,
    owner: str,
    reason: str,
    aggregate_id: str | None = None,
    event_id: str | None = None,
    evidence_sha256: str | None = None,
) -> dict[str, Any]:
    value = {
        "source": source,
        "source_sha256": source_sha256,
        "package_id": package_id,
        "fact_kind": fact_kind,
        "row_id": row_id,
        "fact_sha256": hashlib.sha256(
            canonical_json(row).encode("utf-8")
        ).hexdigest(),
        "disposition": disposition,
        "canonical_owner": owner,
        "reason": reason,
    }
    if aggregate_id is not None:
        value["aggregate_id"] = aggregate_id
    if event_id is not None:
        value["event_id"] = event_id
    if evidence_sha256 is not None:
        value["evidence_sha256"] = evidence_sha256
    return value


def _semantic_blocker(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": "UNRESOLVED_LEGACY_SEMANTIC_FACT",
        "source": row["source"],
        "package_id": row["package_id"],
        "fact_kind": row["fact_kind"],
        "row_id": row["row_id"],
        "reason": row["reason"],
    }


def _unmeasured_token(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in UNMEASURED_VALUES


def _is_unmeasured_result_row(row: dict[str, Any]) -> bool:
    verdict = str(row.get("verdict") or "").upper()
    validity = str(row.get("validity") or "").upper()
    if verdict in {"PASS", "FAIL"}:
        return False
    if validity in {"VALID", "PARTIAL", "RESULT_FAIL", "DIAGNOSTIC_ONLY"}:
        return False
    observed = row.get("value", row.get("measured"))
    return _unmeasured_token(observed) and validity in {
        "",
        "MISSING",
        "UNMEASURED",
    }


def _semantic_experiment_id(
    identities: ExperimentIdentityIndex,
    package_id: str,
    reference: Any,
) -> tuple[str | None, str | None]:
    try:
        value = identities.resolve(package_id, reference)
    except MigrationError as exc:
        return None, str(exc)
    if value is None:
        return None, "semantic fact has no Experiment identifier"
    return value, None


def _planned_result_patch(
    *,
    source: str,
    source_sha256: str,
    package_id: str,
    experiment_id: str,
    fact_kind: str,
    row_id: str,
    row: dict[str, Any],
) -> LegacyRecord:
    key = hashlib.sha256(
        f"{source}:{fact_kind}:{row_id}".encode("utf-8")
    ).hexdigest()[:20]
    return LegacyRecord(
        "AggregatePatched",
        "experiment",
        experiment_id,
        {
            "spec": {
                "result_schema": {
                    "legacy_rows": {
                        key: {
                            "kind": fact_kind,
                            "row_id": row_id,
                            "source": source,
                            "source_sha256": source_sha256,
                            "row": copy.deepcopy(row),
                        }
                    }
                }
            }
        },
        source,
        f"semantic:{package_id}:{fact_kind}:{row_id}",
    )


def _normalized_scalar(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return canonical_json(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        return text


def _same_measurement(expected: Any, actual: Any) -> bool:
    left = _normalized_scalar(expected)
    right = _normalized_scalar(actual)
    if isinstance(left, float) and isinstance(right, float):
        return abs(left - right) <= 1e-12
    return left == right


def _legacy_evidence_path(workspace: Path, value: Any) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = workspace / path
    return path.resolve()


def _measured_result_binding(
    *,
    workspace: Path,
    package_id: str,
    row: dict[str, Any],
    identities: ExperimentIdentityIndex,
    runs: dict[str, LegacyRun],
    finalized: dict[str, LegacyRecord],
) -> tuple[dict[str, Any] | None, str | None]:
    experiment_id, error = _semantic_experiment_id(
        identities,
        package_id,
        row.get("experiment_id", row.get("exp_id")),
    )
    if error is not None:
        return None, error
    candidates = [
        run
        for run in runs.values()
        if run.terminal
        and run.package_id == package_id
        and run.experiment_id == experiment_id
        and run.run_id in finalized
    ]
    requested_run = str(row.get("run_id") or "")
    if requested_run:
        candidates = [run for run in candidates if run.run_id == requested_run]
    evidence_value = (
        row.get("source_artifact")
        or row.get("evidencePath")
        or row.get("evidence_path")
        or row.get("result_json")
    )
    evidence_path = _legacy_evidence_path(workspace, evidence_value)
    if evidence_path is None or not evidence_path.is_file():
        return None, "measured fact requires an existing source artifact"
    bound: list[LegacyRun] = []
    for run in candidates:
        if run.source_dir is None:
            continue
        try:
            evidence_path.relative_to(run.source_dir.resolve())
        except ValueError:
            continue
        bound.append(run)
    if len(bound) != 1:
        return (
            None,
            "measured fact must bind to exactly one terminal Run and source "
            f"artifact; found {len(bound)}",
        )
    run = bound[0]
    result_item = finalized[run.run_id]
    result = result_item.record
    artifact_sha256 = _sha256_file(evidence_path)
    requested_digest = str(
        row.get("source_sha256")
        or row.get("artifact_sha256")
        or row.get("evidence_sha256")
        or row.get("result_sha256")
        or row.get("sha256")
        or ""
    ).lower()
    if requested_digest and requested_digest not in {
        artifact_sha256,
        str(result.get("result_sha256") or "").lower(),
    }:
        return None, "measured fact source/result hash does not match the bound Run"

    verdict = str(row.get("verdict") or "").upper()
    if verdict and verdict != str(result.get("verdict") or "").upper():
        return None, "measured fact verdict disagrees with RunResultFinalized"
    validity = str(row.get("validity") or "").upper()
    if validity and validity != str(result.get("validity") or "").upper():
        return None, "measured fact validity disagrees with RunResultFinalized"
    observed = row.get("value", row.get("measured"))
    if not _unmeasured_token(observed):
        measurements = result.get("measurements")
        measurements = measurements if isinstance(measurements, dict) else {}
        metric = str(
            row.get("metric")
            or row.get("column_key")
            or row.get("column_label")
            or ""
        )
        if metric in measurements:
            measured = measurements[metric]
        elif len(measurements) == 1:
            measured = next(iter(measurements.values()))
        else:
            return None, "measured fact does not identify one finalized measurement"
        if not _same_measurement(observed, measured):
            return None, "measured fact value disagrees with RunResultFinalized"
    return {
        "run_id": run.run_id,
        "experiment_id": experiment_id,
        "aggregate_id": run.run_id,
        "event_id": f"evt_legacy_{result_item.digest[:24]}",
        "result_sha256": result.get("result_sha256"),
        "result_json": result.get("result_json"),
        "evidence_sha256": artifact_sha256,
    }, None


def _learning_evidence(
    *,
    workspace: Path,
    package_id: str,
    row: dict[str, Any],
    runs: dict[str, LegacyRun],
    finalized: dict[str, LegacyRecord],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    raw = row.get("evidence")
    if raw is None:
        raw = row.get("evidence_refs")
    if raw is None and row.get("provenance"):
        raw = [row["provenance"]]
    if not isinstance(raw, list) or not raw:
        return None, "Learning requires evidence for a finalized package Run"
    verified: list[dict[str, Any]] = []
    for item in raw:
        candidate = item if isinstance(item, dict) else {"uri": str(item)}
        requested_run = str(candidate.get("run_id") or "")
        requested_uri = str(
            candidate.get("uri") or candidate.get("provenance") or ""
        )
        requested_digest = str(
            candidate.get("result_sha256") or candidate.get("sha256") or ""
        ).lower()
        if not requested_digest:
            return None, "Learning evidence requires a source or result hash"
        matches: list[tuple[LegacyRun, LegacyRecord, str]] = []
        for run in runs.values():
            result_item = finalized.get(run.run_id)
            if (
                not run.terminal
                or run.package_id != package_id
                or result_item is None
                or (requested_run and requested_run != run.run_id)
            ):
                continue
            result = result_item.record
            digests = {str(result.get("result_sha256") or "").lower()}
            legacy_result = (
                run.source_dir / "result.json"
                if run.source_dir is not None
                else None
            )
            legacy_uri = (
                _relative(legacy_result, workspace)
                if legacy_result is not None and legacy_result.is_file()
                else ""
            )
            if legacy_result is not None and legacy_result.is_file():
                digests.add(_sha256_file(legacy_result))
            uris = {str(result.get("result_json") or ""), legacy_uri}
            if requested_uri and requested_uri not in uris:
                continue
            if requested_digest not in digests:
                continue
            matches.append((run, result_item, str(result.get("result_sha256") or "")))
        if len(matches) != 1:
            return (
                None,
                "Learning evidence must resolve to exactly one finalized Run "
                f"result; found {len(matches)}",
            )
        run, result_item, digest = matches[0]
        verified.append(
            {
                "kind": "RUN_RESULT",
                "run_id": run.run_id,
                "experiment_id": run.experiment_id,
                "result_event_id": f"evt_legacy_{result_item.digest[:24]}",
                "result_sha256": digest,
                "uri": result_item.record.get("result_json"),
            }
        )
    return verified, None


def _append_semantic_row(
    ledger: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    row = _semantic_ledger_row(**kwargs)
    ledger.append(row)
    if row["disposition"] == "unresolved":
        blockers.append(_semantic_blocker(row))
    return row


def _result_semantic_row(
    *,
    workspace: Path,
    source: str,
    source_sha256: str,
    package_id: str,
    fact_kind: str,
    row_id: str,
    row: dict[str, Any],
    identities: ExperimentIdentityIndex,
    runs: dict[str, LegacyRun],
    finalized: dict[str, LegacyRecord],
    extra: list[LegacyRecord],
    ledger: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> bool:
    if _is_unmeasured_result_row(row):
        experiment_id, error = _semantic_experiment_id(
            identities,
            package_id,
            row.get("experiment_id", row.get("exp_id")),
        )
        if error is not None:
            _append_semantic_row(
                ledger,
                blockers,
                source=source,
                source_sha256=source_sha256,
                package_id=package_id,
                fact_kind=fact_kind,
                row_id=row_id,
                row=row,
                disposition="unresolved",
                owner="Experiment",
                reason=error,
            )
            return False
        assert experiment_id is not None
        patch = _planned_result_patch(
            source=source,
            source_sha256=source_sha256,
            package_id=package_id,
            experiment_id=experiment_id,
            fact_kind=fact_kind,
            row_id=row_id,
            row=row,
        )
        extra.append(patch)
        _append_semantic_row(
            ledger,
            blockers,
            source=source,
            source_sha256=source_sha256,
            package_id=package_id,
            fact_kind=fact_kind,
            row_id=row_id,
            row=row,
            disposition="derivable",
            owner="Experiment",
            reason="planned/unmeasured row stored in Experiment.spec.result_schema",
            aggregate_id=experiment_id,
            event_id=f"evt_legacy_{patch.digest[:24]}",
        )
        return True
    binding, error = _measured_result_binding(
        workspace=workspace,
        package_id=package_id,
        row=row,
        identities=identities,
        runs=runs,
        finalized=finalized,
    )
    if error is not None:
        _append_semantic_row(
            ledger,
            blockers,
            source=source,
            source_sha256=source_sha256,
            package_id=package_id,
            fact_kind=fact_kind,
            row_id=row_id,
            row=row,
            disposition="unresolved",
            owner="RunResultFinalized",
            reason=error,
        )
        return False
    assert binding is not None
    _append_semantic_row(
        ledger,
        blockers,
        source=source,
        source_sha256=source_sha256,
        package_id=package_id,
        fact_kind=fact_kind,
        row_id=row_id,
        row=row,
        disposition="canonicalized",
        owner="RunResultFinalized",
        reason="row reconciled with one terminal Run result and source artifact",
        aggregate_id=binding["aggregate_id"],
        event_id=binding["event_id"],
        evidence_sha256=binding["evidence_sha256"],
    )
    return True


def _structured_semantic_rows(
    *,
    item: LegacyRecord,
    record: dict[str, Any],
    workspace: Path,
    identities: ExperimentIdentityIndex,
    runs: dict[str, LegacyRun],
    finalized: dict[str, LegacyRecord],
    extra: list[LegacyRecord],
    ledger: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    package_id = item.aggregate_id
    source_sha256 = _semantic_source_sha(workspace, item.source, item.digest)
    updated = copy.deepcopy(record)
    implementation = updated.get("implementation")
    nested_changes = (
        implementation.get("changes")
        if isinstance(implementation, dict) and "changes" in implementation
        else None
    )
    for field, owner in PACKAGE_SHADOW_OWNERS.items():
        field_present = field in updated
        if not field_present and not (
            field == "implementationReviews" and nested_changes is not None
        ):
            continue
        raw_rows = updated.get(field)
        if field == "implementationReviews" and nested_changes is not None:
            if field_present and isinstance(raw_rows, list) and isinstance(
                nested_changes, list
            ):
                raw_rows = [*raw_rows, *nested_changes]
            elif not field_present:
                raw_rows = nested_changes
        if not isinstance(raw_rows, list):
            _append_semantic_row(
                ledger,
                blockers,
                source=item.source,
                source_sha256=source_sha256,
                package_id=package_id,
                fact_kind=f"package.{field}",
                row_id="$field",
                row=raw_rows,
                disposition="unresolved",
                owner=owner,
                reason=f"Package shadow field {field} must be an array",
            )
            continue
        if not raw_rows:
            updated.pop(field, None)
            if field == "implementationReviews" and nested_changes is not None:
                implementation = updated.get("implementation")
                if isinstance(implementation, dict):
                    implementation = copy.deepcopy(implementation)
                    implementation.pop("changes", None)
                    if implementation:
                        updated["implementation"] = implementation
                    else:
                        updated.pop("implementation", None)
            _append_semantic_row(
                ledger,
                blockers,
                source=item.source,
                source_sha256=source_sha256,
                package_id=package_id,
                fact_kind=f"package.{field}",
                row_id="$empty",
                row=[],
                disposition="derivable",
                owner=owner,
                reason="empty shadow field removed; canonical owner remains authoritative",
            )
            continue
        resolved = True
        for index, raw in enumerate(raw_rows, start=1):
            row_id = _semantic_row_id(raw, index)
            fact_kind = (
                "package.implementation.changes"
                if field == "implementationReviews"
                and nested_changes is not None
                and not field_present
                else f"package.{field}"
            )
            if not isinstance(raw, dict):
                _append_semantic_row(
                    ledger,
                    blockers,
                    source=item.source,
                    source_sha256=source_sha256,
                    package_id=package_id,
                    fact_kind=fact_kind,
                    row_id=row_id,
                    row=raw,
                    disposition="unresolved",
                    owner=owner,
                    reason="structured semantic row must be an object",
                )
                resolved = False
                continue
            row = copy.deepcopy(raw)
            if field in {"methodsTried", "resultGateRows", "resultBlocks"}:
                resolved = (
                    _result_semantic_row(
                        workspace=workspace,
                        source=item.source,
                        source_sha256=source_sha256,
                        package_id=package_id,
                        fact_kind=fact_kind,
                        row_id=row_id,
                        row=row,
                        identities=identities,
                        runs=runs,
                        finalized=finalized,
                        extra=extra,
                        ledger=ledger,
                        blockers=blockers,
                    )
                    and resolved
                )
                continue
            if field == "analysisInsights":
                local_id = str(row.get("id") or row.get("slug") or "")
                evidence, error = _learning_evidence(
                    workspace=workspace,
                    package_id=package_id,
                    row=row,
                    runs=runs,
                    finalized=finalized,
                )
                if not local_id or not str(row.get("title") or "").strip():
                    error = "Learning requires id/slug and title"
                if error is not None:
                    _append_semantic_row(
                        ledger,
                        blockers,
                        source=item.source,
                        source_sha256=source_sha256,
                        package_id=package_id,
                        fact_kind=fact_kind,
                        row_id=row_id,
                        row=row,
                        disposition="unresolved",
                        owner="Learning",
                        reason=error,
                    )
                    resolved = False
                    continue
                aggregate_id = f"{package_id}::learning::{local_id}"
                canonical = {
                    **row,
                    "id": aggregate_id,
                    "local_id": local_id,
                    "package_id": package_id,
                    "kind": "insight",
                    "status": "ACTIVE",
                    "evidence": evidence,
                    "provenance": evidence[0]["uri"],
                }
                typed = LegacyRecord(
                    "LearningRecorded",
                    "learning",
                    aggregate_id,
                    canonical,
                    item.source,
                    f"semantic:{package_id}:learning:{local_id}",
                )
                extra.append(typed)
                _append_semantic_row(
                    ledger,
                    blockers,
                    source=item.source,
                    source_sha256=source_sha256,
                    package_id=package_id,
                    fact_kind=fact_kind,
                    row_id=row_id,
                    row=row,
                    disposition="canonicalized",
                    owner="Learning",
                    reason="structured insight imported with verified Run evidence",
                    aggregate_id=aggregate_id,
                    event_id=f"evt_legacy_{typed.digest[:24]}",
                )
                continue
            if field == "implementationReviews":
                local_id = str(row.get("id") or row.get("change_id") or "")
                owned = row.get("owned_files", row.get("ownedFiles"))
                review = row.get("review")
                if not isinstance(review, dict):
                    review = {
                        "status": row.get("status"),
                        "summary": row.get("summary"),
                    }
                validating = row.get(
                    "validating_experiments",
                    row.get("validatingExperiments"),
                )
                error = None
                canonical_validating: list[str] = []
                if not local_id:
                    error = "Change requires id/change_id"
                elif not isinstance(owned, list) or not owned or not all(
                    isinstance(path, str) and path.strip() for path in owned
                ):
                    error = "Change requires non-empty owned_files"
                elif not isinstance(review, dict) or not any(
                    str(value or "").strip() for value in review.values()
                ):
                    error = "Change requires a non-empty review"
                elif not isinstance(validating, list) or not validating:
                    error = "Change requires validating_experiments"
                else:
                    for reference in validating:
                        experiment_id, identity_error = _semantic_experiment_id(
                            identities,
                            package_id,
                            reference,
                        )
                        if identity_error is not None:
                            error = identity_error
                            break
                        assert experiment_id is not None
                        canonical_validating.append(experiment_id)
                if error is not None:
                    _append_semantic_row(
                        ledger,
                        blockers,
                        source=item.source,
                        source_sha256=source_sha256,
                        package_id=package_id,
                        fact_kind=fact_kind,
                        row_id=row_id,
                        row=row,
                        disposition="unresolved",
                        owner="Change",
                        reason=error,
                    )
                    resolved = False
                    continue
                aggregate_id = f"{package_id}::change::{local_id}"
                canonical = {
                    **row,
                    "id": aggregate_id,
                    "local_id": local_id,
                    "package_id": package_id,
                    "owned_files": list(dict.fromkeys(owned)),
                    "review": copy.deepcopy(review),
                    "validating_experiments": list(
                        dict.fromkeys(canonical_validating)
                    ),
                    "status": row.get("status") or "RECORDED",
                }
                typed = LegacyRecord(
                    "AggregateUpserted",
                    "change",
                    aggregate_id,
                    canonical,
                    item.source,
                    f"semantic:{package_id}:change:{local_id}",
                )
                extra.append(typed)
                _append_semantic_row(
                    ledger,
                    blockers,
                    source=item.source,
                    source_sha256=source_sha256,
                    package_id=package_id,
                    fact_kind=fact_kind,
                    row_id=row_id,
                    row=row,
                    disposition="canonicalized",
                    owner="Change",
                    reason="structured implementation review satisfies Change contract",
                    aggregate_id=aggregate_id,
                    event_id=f"evt_legacy_{typed.digest[:24]}",
                )
                continue
            actor = row.get("actor")
            evidence = row.get("evidence")
            ack_type = str(row.get("ack_type") or "")
            value = row.get("value", row.get("to"))
            actor_ok = (
                isinstance(actor, dict)
                and actor.get("type") in {"user", "agent", "system"}
                and isinstance(actor.get("id"), str)
                and bool(actor["id"])
            )
            error = None
            if not ack_type or value in (None, ""):
                error = "Decision acknowledgement requires ack_type and value/to"
            elif not actor_ok:
                error = "Decision acknowledgement requires an explicit typed actor"
            elif not isinstance(evidence, list) or not evidence:
                error = "Decision acknowledgement requires explicit evidence"
            elif ack_type.upper() in {"LAUNCH_ACK", "READY_TO_LAUNCH_ACK"} and (
                actor.get("type") != "user"
                or str(value).upper() not in {"ACKNOWLEDGED", "ACCEPTED"}
            ):
                error = "launch acknowledgement requires a user actor and accepted value"
            if error is not None:
                _append_semantic_row(
                    ledger,
                    blockers,
                    source=item.source,
                    source_sha256=source_sha256,
                    package_id=package_id,
                    fact_kind=fact_kind,
                    row_id=row_id,
                    row=row,
                    disposition="unresolved",
                    owner="Decision",
                    reason=error,
                )
                resolved = False
                continue
            local_id = str(row.get("id") or f"{ack_type}:{row.get('page') or ''}")
            aggregate_id = (
                local_id
                if local_id.startswith(f"{package_id}::")
                else f"{package_id}::ack::{local_id}"
            )
            canonical = {
                **row,
                "id": aggregate_id,
                "package_id": package_id,
                "kind": (
                    ack_type.upper()
                    if ack_type.upper() in {"LAUNCH_ACK", "READY_TO_LAUNCH_ACK"}
                    else "ACKNOWLEDGEMENT"
                ),
                "ack_type": ack_type,
                "value": copy.deepcopy(value),
                "actor": copy.deepcopy(actor),
                "evidence": copy.deepcopy(evidence),
                "status": row.get("status") or "ACKNOWLEDGED",
            }
            typed = LegacyRecord(
                "DecisionRecorded",
                "decision",
                aggregate_id,
                canonical,
                item.source,
                f"semantic:{package_id}:decision:{local_id}",
            )
            extra.append(typed)
            _append_semantic_row(
                ledger,
                blockers,
                source=item.source,
                source_sha256=source_sha256,
                package_id=package_id,
                fact_kind=fact_kind,
                row_id=row_id,
                row=row,
                disposition="canonicalized",
                owner="Decision",
                reason="structured acknowledgement satisfies Decision contract",
                aggregate_id=aggregate_id,
                event_id=f"evt_legacy_{typed.digest[:24]}",
            )
        if resolved:
            updated.pop(field, None)
            if field == "implementationReviews" and nested_changes is not None:
                implementation = updated.get("implementation")
                if isinstance(implementation, dict):
                    implementation = copy.deepcopy(implementation)
                    implementation.pop("changes", None)
                    if implementation:
                        updated["implementation"] = implementation
                    else:
                        updated.pop("implementation", None)
    return updated


def _fact_archive_semantics(
    *,
    item: LegacyRecord,
    workspace: Path,
    identities: ExperimentIdentityIndex,
    schema_owners: dict[tuple[str, str], str],
    runs: dict[str, LegacyRun],
    finalized: dict[str, LegacyRecord],
    extra: list[LegacyRecord],
    ledger: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    package_id = item.aggregate_id
    store = item.record.get("legacy_fact_store")
    files = store.get("files") if isinstance(store, dict) else None
    if not isinstance(files, dict):
        return
    for relative, envelope in sorted(files.items()):
        if not isinstance(envelope, dict):
            continue
        source = item.source
        source_sha256 = str(envelope.get("sha256") or item.digest)
        data = envelope.get("data")
        name = Path(str(relative)).name
        if envelope.get("format") == "package-facts" and isinstance(data, dict):
            raw_schemas = data.get("resultSchemas")
            if raw_schemas is not None and not isinstance(raw_schemas, dict):
                _append_semantic_row(
                    ledger,
                    blockers,
                    source=source,
                    source_sha256=source_sha256,
                    package_id=package_id,
                    fact_kind="facts.result_schema",
                    row_id="$field",
                    row=raw_schemas,
                    disposition="unresolved",
                    owner="Experiment",
                    reason="resultSchemas must be an object",
                )
            schemas = raw_schemas if isinstance(raw_schemas, dict) else {}
            table_owners: dict[str, str] = {}
            for index, (schema_id, raw) in enumerate(sorted(schemas.items()), start=1):
                row_id = str(schema_id or index)
                if not isinstance(raw, dict):
                    _append_semantic_row(
                        ledger,
                        blockers,
                        source=source,
                        source_sha256=source_sha256,
                        package_id=package_id,
                        fact_kind="facts.result_schema",
                        row_id=row_id,
                        row=raw,
                        disposition="unresolved",
                        owner="Experiment",
                        reason="result schema must be an object",
                    )
                    continue
                experiment_ref = raw.get("expId", raw.get("exp_id"))
                if experiment_ref in (None, ""):
                    experiment_id = schema_owners.get((package_id, row_id))
                    error = (
                        None
                        if experiment_id is not None
                        else "result schema has no expId or unique Experiment resultSchemaRef"
                    )
                else:
                    experiment_id, error = _semantic_experiment_id(
                        identities,
                        package_id,
                        experiment_ref,
                    )
                if error is not None:
                    _append_semantic_row(
                        ledger,
                        blockers,
                        source=source,
                        source_sha256=source_sha256,
                        package_id=package_id,
                        fact_kind="facts.result_schema",
                        row_id=row_id,
                        row=raw,
                        disposition="unresolved",
                        owner="Experiment",
                        reason=error,
                    )
                    continue
                assert experiment_id is not None
                patch = _planned_result_patch(
                    source=source,
                    source_sha256=source_sha256,
                    package_id=package_id,
                    experiment_id=experiment_id,
                    fact_kind="facts.result_schema",
                    row_id=row_id,
                    row=raw,
                )
                extra.append(patch)
                if raw.get("tableId"):
                    table_owners[str(raw["tableId"])] = experiment_id
                _append_semantic_row(
                    ledger,
                    blockers,
                    source=source,
                    source_sha256=source_sha256,
                    package_id=package_id,
                    fact_kind="facts.result_schema",
                    row_id=row_id,
                    row=raw,
                    disposition="derivable",
                    owner="Experiment",
                    reason="result schema stored in Experiment.spec.result_schema",
                    aggregate_id=experiment_id,
                    event_id=f"evt_legacy_{patch.digest[:24]}",
                )
            tables = data.get("resultTables")
            if tables is not None and not isinstance(tables, list):
                _append_semantic_row(
                    ledger,
                    blockers,
                    source=source,
                    source_sha256=source_sha256,
                    package_id=package_id,
                    fact_kind="facts.result_table",
                    row_id="$field",
                    row=tables,
                    disposition="unresolved",
                    owner="Experiment",
                    reason="resultTables must be an array",
                )
            if isinstance(tables, list):
                for index, table_id in enumerate(tables, start=1):
                    owner_id = table_owners.get(str(table_id))
                    _append_semantic_row(
                        ledger,
                        blockers,
                        source=source,
                        source_sha256=source_sha256,
                        package_id=package_id,
                        fact_kind="facts.result_table",
                        row_id=str(table_id or index),
                        row=table_id,
                        disposition="derivable" if owner_id else "unresolved",
                        owner="Experiment",
                        reason=(
                            "table declaration is owned by imported result schema"
                            if owner_id
                            else "result table declaration has no owning schema"
                        ),
                        aggregate_id=owner_id,
                    )
            if not schemas and not tables:
                semantic_fields = sorted(
                    field
                    for field in PACKAGE_SHADOW_OWNERS
                    if data.get(field) not in (None, [], {})
                )
                for field in semantic_fields:
                    _append_semantic_row(
                        ledger,
                        blockers,
                        source=source,
                        source_sha256=source_sha256,
                        package_id=package_id,
                        fact_kind=f"facts.{field}",
                        row_id="$field",
                        row=data[field],
                        disposition="unresolved",
                        owner=PACKAGE_SHADOW_OWNERS[field],
                        reason="semantic field must be migrated from structured Package inventory",
                    )
                _append_semantic_row(
                    ledger,
                    blockers,
                    source=source,
                    source_sha256=source_sha256,
                    package_id=package_id,
                    fact_kind="facts.projection_metadata",
                    row_id="$metadata",
                    row=data,
                    disposition="derivable",
                    owner="raw-provenance",
                    reason="renderer metadata is retained only in raw provenance archive",
                )
            continue
        if envelope.get("format") == "csv" and isinstance(data, list):
            if name == "methods_tried.csv":
                fact_kind = "csv.methods_tried"
            elif name == "result_gate.csv":
                fact_kind = "csv.result_gate"
            elif name.startswith("result_table_") and name.endswith(".csv"):
                fact_kind = "csv.result_table"
            else:
                fact_kind = ""
            if fact_kind:
                if not data:
                    _append_semantic_row(
                        ledger,
                        blockers,
                        source=source,
                        source_sha256=source_sha256,
                        package_id=package_id,
                        fact_kind=fact_kind,
                        row_id="$empty",
                        row=[],
                        disposition="derivable",
                        owner="RunResultFinalized",
                        reason="empty projection table has no semantic facts",
                    )
                for index, raw in enumerate(data, start=1):
                    if not isinstance(raw, dict):
                        _append_semantic_row(
                            ledger,
                            blockers,
                            source=source,
                            source_sha256=source_sha256,
                            package_id=package_id,
                            fact_kind=fact_kind,
                            row_id=str(index),
                            row=raw,
                            disposition="unresolved",
                            owner="RunResultFinalized",
                            reason="result CSV row must be an object",
                        )
                        continue
                    _result_semantic_row(
                        workspace=workspace,
                        source=source,
                        source_sha256=source_sha256,
                        package_id=package_id,
                        fact_kind=fact_kind,
                        row_id=_semantic_row_id(raw, index),
                        row=raw,
                        identities=identities,
                        runs=runs,
                        finalized=finalized,
                        extra=extra,
                        ledger=ledger,
                        blockers=blockers,
                    )
                continue
            if not data:
                _append_semantic_row(
                    ledger,
                    blockers,
                    source=source,
                    source_sha256=source_sha256,
                    package_id=package_id,
                    fact_kind=f"csv.{Path(name).stem}",
                    row_id="$empty",
                    row=[],
                    disposition="derivable",
                    owner="raw-provenance",
                    reason="empty auxiliary projection has no semantic facts",
                )
            else:
                for index, raw in enumerate(data, start=1):
                    _append_semantic_row(
                        ledger,
                        blockers,
                        source=source,
                        source_sha256=source_sha256,
                        package_id=package_id,
                        fact_kind=f"csv.{Path(name).stem}",
                        row_id=_semantic_row_id(raw, index),
                        row=raw,
                        disposition="unresolved",
                        owner="typed-runtime-aggregate",
                        reason="non-empty auxiliary fact table has no deterministic typed adapter",
                    )
            continue
        empty = data in (None, "", [], {})
        _append_semantic_row(
            ledger,
            blockers,
            source=source,
            source_sha256=source_sha256,
            package_id=package_id,
            fact_kind=f"archive.{name}",
            row_id="$file",
            row=data,
            disposition="derivable" if empty else "unresolved",
            owner="raw-provenance",
            reason=(
                "empty archive file has no semantic facts"
                if empty
                else "non-empty archive file has no deterministic typed adapter"
            ),
        )


def _semantic_fact_analysis(
    records: list[LegacyRecord],
    *,
    workspace: Path,
    identities: ExperimentIdentityIndex,
    runs: list[LegacyRun],
) -> SemanticFactAnalysis:
    finalized = {
        item.aggregate_id: item
        for item in records
        if item.event_type == "RunResultFinalized"
        and item.aggregate_type == "run"
    }
    run_index = {run.run_id: run for run in runs}
    schema_owner_candidates: dict[tuple[str, str], set[str]] = {}
    for item in records:
        if item.aggregate_type != "experiment":
            continue
        package_id = item.record.get("package_id")
        if not isinstance(package_id, str) or not package_id:
            continue
        spec = item.record.get("spec")
        spec = spec if isinstance(spec, dict) else {}
        references = [
            item.record.get("resultSchemaRef"),
            spec.get("resultSchemaRef"),
        ]
        inline = item.record.get("resultSchema")
        if isinstance(inline, dict):
            references.append(inline.get("id"))
        for reference in references:
            if isinstance(reference, str) and reference:
                schema_owner_candidates.setdefault(
                    (package_id, str(reference)),
                    set(),
                ).add(item.aggregate_id)
    schema_owners = {
        key: next(iter(candidates))
        for key, candidates in schema_owner_candidates.items()
        if len(candidates) == 1
    }
    transformed: list[LegacyRecord] = []
    extra: list[LegacyRecord] = []
    ledger: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for item in records:
        if (
            item.event_type == "AggregateImported"
            and item.aggregate_type == "package"
        ):
            record = _structured_semantic_rows(
                item=item,
                record=item.record,
                workspace=workspace,
                identities=identities,
                runs=run_index,
                finalized=finalized,
                extra=extra,
                ledger=ledger,
                blockers=blockers,
            )
            item = LegacyRecord(
                item.event_type,
                item.aggregate_type,
                item.aggregate_id,
                record,
                item.source,
                item.identity,
            )
        transformed.append(item)
        if (
            item.event_type == "AggregatePatched"
            and item.aggregate_type == "package"
            and "legacy_fact_store" in item.record
        ):
            _fact_archive_semantics(
                item=item,
                workspace=workspace,
                identities=identities,
                schema_owners=schema_owners,
                runs=run_index,
                finalized=finalized,
                extra=extra,
                ledger=ledger,
                blockers=blockers,
            )
    ordered_ledger = sorted(
        ledger,
        key=lambda row: (
            str(row.get("source")),
            str(row.get("package_id")),
            str(row.get("fact_kind")),
            str(row.get("row_id")),
        ),
    )
    ordered_blockers = sorted(
        blockers,
        key=lambda row: (
            str(row.get("source")),
            str(row.get("package_id")),
            str(row.get("fact_kind")),
            str(row.get("row_id")),
        ),
    )
    return SemanticFactAnalysis(
        records=tuple([*transformed, *extra]),
        ledger=tuple(ordered_ledger),
        blockers=tuple(ordered_blockers),
    )


def _learned_rule_records(outputs: Path, workspace: Path) -> Iterator[LegacyRecord]:
    path = outputs / "_learned" / "rules.md"
    if not path.exists():
        return
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith(("- ", "* ")):
            continue
        content = stripped[2:].strip()
        if not content:
            continue
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        rule_id = f"legacy-learned-{digest[:20]}"
        yield LegacyRecord(
            "AggregateImported",
            "rule",
            rule_id,
            {
                "id": rule_id,
                "status": "ACTIVE",
                "level": "project",
                "kind": "constraint",
                "title": content[:80],
                "text": content,
                "content": content,
                "origin": "legacy-learned",
                "legacy_line": index,
            },
            _relative(path, workspace),
            f"learned-rule:{index}:{digest}",
        )


def _brainstorm_aux_records(outputs: Path, workspace: Path) -> Iterator[LegacyRecord]:
    root = outputs / "_brainstorm"
    if not root.exists():
        return
    for candidates_path in sorted(root.glob("*/candidates.json")):
        value = _json(candidates_path)
        rows = value.get("candidates") if isinstance(value, dict) else value
        if not isinstance(rows, list):
            raise MigrationError(f"{candidates_path}: candidates must be an array")
        slug = candidates_path.parent.name
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise MigrationError(f"{candidates_path}:{index}: candidate must be an object")
            local_id = row.get("id") or row.get("idea_id") or index
            aggregate_id = f"legacy-candidate:{slug}:{local_id}"
            record = copy.deepcopy(row)
            record.update(
                {
                    "id": aggregate_id,
                    "legacy_candidate_id": str(local_id),
                    "legacy_brainstorm_slug": slug,
                }
            )
            yield LegacyRecord(
                "AggregateImported",
                "brainstorm",
                aggregate_id,
                record,
                _relative(candidates_path, workspace),
                f"{slug}:candidate:{local_id}",
            )
    for verdict_path in sorted(root.glob("*/verdicts/*.json")):
        row = _json(verdict_path)
        if not isinstance(row, dict):
            raise MigrationError(f"{verdict_path}: ranking verdict must be an object")
        identity = row.get("ranking_id") or verdict_path.stem
        aggregate_id = f"legacy-ranking:{verdict_path.parent.parent.name}:{identity}"
        yield LegacyRecord(
            "AggregateImported",
            "decision",
            aggregate_id,
            {
                "id": aggregate_id,
                "decision_type": "LEGACY_BRAINSTORM_RANKING",
                "legacy_record": row,
            },
            _relative(verdict_path, workspace),
            str(identity),
        )


def _selfevolve_records(outputs: Path, workspace: Path) -> Iterator[LegacyRecord]:
    """Import legacy self-evolve memory while leaving executable bundles inert."""
    root = outputs / "_selfevolve"
    if not root.exists():
        return

    transition_paths = (
        root / "rules" / "transitions.jsonl",
        root / "skills" / "transitions.jsonl",
    )
    transitions: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for path in transition_paths:
        for index, row in enumerate(_jsonl(path), start=1):
            store_kind = str(row.get("store") or path.parent.name.removesuffix("s"))
            entity_id = row.get("entity_id")
            version = row.get("entity_version")
            if not entity_id or version in {None, ""}:
                raise MigrationError(f"{path}:{index}: transition has no entity/version")
            key = (store_kind, str(entity_id), str(version))
            transitions.setdefault(key, []).append(copy.deepcopy(row))
            decision_id = str(
                row.get("transition_id")
                or f"legacy-transition-{store_kind}-{entity_id}-{version}-{index}"
            )
            yield LegacyRecord(
                "AggregateImported",
                "decision",
                decision_id,
                {
                    "id": decision_id,
                    "decision_type": "LEGACY_SELF_EVOLVE_TRANSITION",
                    "subject_id": f"{entity_id}@{version}",
                    "legacy_record": row,
                },
                _relative(path, workspace),
                f"transition:{index}:{decision_id}",
            )

    imported_rule_keys: set[tuple[str, str]] = set()
    rule_paths = sorted(
        {
            *root.glob("rules/candidates/*/*/rule.json"),
            *root.glob("rules/releases/*/*/rule.json"),
        }
    )
    for path in rule_paths:
        row = _json(path)
        if not isinstance(row, dict):
            raise MigrationError(f"{path}: self-evolve Rule must be an object")
        entity_id = str(row.get("id") or path.parents[1].name)
        version = str(row.get("version") or path.parent.name)
        if (entity_id, version) in imported_rule_keys:
            continue
        history = transitions.get(("rule", entity_id, version), [])
        state = str(history[-1].get("to_state")) if history else "CANDIDATE"
        status = (
            "ACTIVE"
            if state == "RULE_ACTIVE"
            else "RETIRED"
            if state in {"INVALIDATED", "RETIRED", "SUSPENDED"}
            else "PROMOTED"
        )
        scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
        packages = scope.get("packages") if isinstance(scope, dict) else []
        level = "project" if packages == ["*"] else "package"
        aggregate_id = f"{entity_id}@{version}"
        record = copy.deepcopy(row)
        record.update(
            {
                "id": aggregate_id,
                "legacy_rule_id": entity_id,
                "version": version,
                "status": status,
                "level": (
                    row.get("level")
                    if row.get("level") in enum("rule_level")
                    else level
                ),
                "kind": (
                    row.get("kind")
                    if row.get("kind") in enum("rule_kind")
                    else "constraint" if level == "project" else "binding"
                ),
                "legacy_lifecycle": state,
                "legacy_transitions": history,
            }
        )
        yield LegacyRecord(
            "AggregateImported",
            "rule",
            aggregate_id,
            record,
            _relative(path, workspace),
            f"selfevolve-rule:{entity_id}@{version}",
        )
        imported_rule_keys.add((entity_id, version))

    for (store_kind, entity_id, version), history in sorted(transitions.items()):
        if store_kind == "rule" and (entity_id, version) not in imported_rule_keys:
            state = str(history[-1].get("to_state"))
            aggregate_id = f"{entity_id}@{version}"
            yield LegacyRecord(
                "AggregateImported",
                "rule",
                aggregate_id,
                {
                    "id": aggregate_id,
                    "legacy_rule_id": entity_id,
                    "version": version,
                    "status": "ACTIVE" if state == "RULE_ACTIVE" else "PROMOTED",
                    "level": "project",
                    "kind": "constraint",
                    "legacy_lifecycle": state,
                    "legacy_transitions": history,
                    "migration_incomplete": "candidate rule.json was absent",
                },
                _relative(root / "rules" / "transitions.jsonl", workspace),
                f"selfevolve-rule-placeholder:{entity_id}@{version}",
            )

    for path, decision_type in (
        (root / "approvals" / "approvals.jsonl", "LEGACY_SELF_EVOLVE_APPROVAL"),
        (root / "events" / "events.jsonl", "LEGACY_SELF_EVOLVE_OBSERVATION"),
    ):
        for index, row in enumerate(_jsonl(path), start=1):
            identity = (
                row.get("approval_id")
                or row.get("event_id")
                or hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()[:20]
            )
            aggregate_type = "decision" if "APPROVAL" in decision_type else "learning"
            aggregate_id = f"legacy-selfevolve:{identity}"
            yield LegacyRecord(
                "AggregateImported",
                aggregate_type,
                aggregate_id,
                {
                    "id": aggregate_id,
                    "record_type": decision_type,
                    "legacy_record": row,
                },
                _relative(path, workspace),
                f"{decision_type}:{index}:{identity}",
            )

    for path in sorted(root.glob("evidence/**/*.json")):
        row = _json(path)
        if not isinstance(row, dict):
            raise MigrationError(f"{path}: self-evolve evidence must be an object")
        identity = row.get("evidence_id") or path.stem
        aggregate_id = f"legacy-selfevolve-evidence:{identity}"
        yield LegacyRecord(
            "AggregateImported",
            "decision",
            aggregate_id,
            {
                "id": aggregate_id,
                "decision_type": "LEGACY_SELF_EVOLVE_EVIDENCE",
                "legacy_record": row,
            },
            _relative(path, workspace),
            str(identity),
        )

    # Skill manifests are retained as inert knowledge. Migration never installs
    # or activates executable content.
    skill_paths = sorted(
        {
            *root.glob("skills/candidates/*/*/manifest.json"),
            *root.glob("skills/releases/*/*/manifest.json"),
        }
    )
    imported_skills: set[str] = set()
    for path in skill_paths:
        row = _json(path)
        if not isinstance(row, dict):
            raise MigrationError(f"{path}: skill manifest must be an object")
        identity = f"{row.get('id') or path.parents[1].name}@{row.get('version') or path.parent.name}"
        if identity in imported_skills:
            continue
        imported_skills.add(identity)
        aggregate_id = f"legacy-skill:{identity}"
        yield LegacyRecord(
            "AggregateImported",
            "learning",
            aggregate_id,
            {
                "id": aggregate_id,
                "kind": "LEGACY_EXECUTABLE_SKILL_MANIFEST",
                "legacy_record": row,
                "activation": "INERT_AFTER_MIGRATION",
            },
            _relative(path, workspace),
            identity,
        )

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        classification, _, _ = _classification(path, workspace)
        if classification != "selfevolve-support-evidence":
            continue
        if path.suffix.lower() == ".json":
            value: Any = _json(path)
        elif path.suffix.lower() == ".jsonl":
            value = _jsonl(path)
        else:
            value = path.read_text(encoding="utf-8")
        relative = _relative(path, workspace)
        identity = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]
        aggregate_id = f"legacy-selfevolve-support:{identity}"
        yield LegacyRecord(
            "AggregateImported",
            "learning",
            aggregate_id,
            {
                "id": aggregate_id,
                "kind": "LEGACY_SELF_EVOLVE_SUPPORT_EVIDENCE",
                "legacy_path": relative,
                "legacy_record": value,
                "sha256": _sha256_file(path),
            },
            relative,
            aggregate_id,
        )


def _resource_records(
    outputs: Path,
    workspace: Path,
    *,
    experiment_identities: ExperimentIdentityIndex,
) -> Iterator[LegacyRecord]:
    resource_root = outputs / "_resources"
    server_path = resource_root / "servers.json"
    servers = _json(server_path, [])
    if not isinstance(servers, list):
        raise MigrationError(f"{server_path}: server registry must be an array")
    source = _relative(server_path, workspace)
    for server in servers:
        if not isinstance(server, dict) or not server.get("name"):
            raise MigrationError(f"{server_path}: invalid server row")
        yield LegacyRecord(
            "AggregateImported",
            "resource",
            str(server["name"]),
            dict(server),
            source,
            str(server["name"]),
        )

    ledger_path = resource_root / "allocations.jsonl"
    folded: dict[str, dict[str, Any]] = {}
    history: dict[str, list[dict[str, Any]]] = {}
    for row in _jsonl(ledger_path):
        alloc_id = row.get("alloc_id")
        if not alloc_id:
            raise MigrationError(f"{ledger_path}: allocation row has no alloc_id")
        history.setdefault(str(alloc_id), []).append(row)
        if row.get("op") == "allocate":
            folded[str(alloc_id)] = dict(row)
            folded[str(alloc_id)]["status"] = "OPEN"
        elif row.get("op") == "link" and str(alloc_id) in folded:
            folded[str(alloc_id)].update(
                {key: value for key, value in row.items() if key not in {"op", "t"}}
            )
        elif row.get("op") == "release" and str(alloc_id) in folded:
            folded[str(alloc_id)]["status"] = "RELEASED"
            folded[str(alloc_id)]["outcome"] = row.get("outcome")
            folded[str(alloc_id)]["released_at"] = row.get("t")
    source = _relative(ledger_path, workspace)
    for alloc_id, record in folded.items():
        package_id = record.get("package_id") or record.get("pkg")
        local_experiment_id = record.get("experiment_local_id") or record.get("exp_id")
        explicit_experiment_id = record.get("experiment_id")
        if package_id:
            package_id = str(package_id)
            record["package_id"] = package_id
        if package_id and (
            local_experiment_id is not None
            or explicit_experiment_id is not None
        ):
            canonical_experiment_id = experiment_identities.resolve(
                package_id,
                local_experiment_id,
                explicit_experiment_id,
            )
            if canonical_experiment_id is None:
                raise MigrationError(
                    f"allocation {alloc_id} has no canonical Experiment identity"
                )
            if local_experiment_id is None:
                local_experiment_id = experiment_identities.local_id(
                    package_id,
                    canonical_experiment_id,
                )
            record["experiment_local_id"] = str(local_experiment_id)
            record["experiment_id"] = canonical_experiment_id
        record["history"] = history[alloc_id]
        yield LegacyRecord(
            "AggregateImported",
            "resource_allocation",
            alloc_id,
            record,
            source,
            alloc_id,
        )


def _campaign_records(outputs: Path, workspace: Path) -> Iterator[LegacyRecord]:
    auto_root = outputs / "_auto"
    if not auto_root.exists():
        return
    for ledger in sorted(auto_root.glob("*/campaign.jsonl")):
        cycles = _jsonl(ledger)
        direction_id = next(
            (str(row["direction_id"]) for row in cycles if row.get("direction_id")),
            ledger.parent.name,
        )
        record = {
            "id": direction_id,
            "direction_id": direction_id,
            "cycles": cycles,
            "status": "RUNNING" if cycles else "IDLE",
        }
        yield LegacyRecord(
            "AggregateImported",
            "campaign",
            direction_id,
            record,
            _relative(ledger, workspace),
            direction_id,
        )


def _discover_legacy_runs(
    outputs: Path,
    workspace: Path,
    *,
    experiment_identities: ExperimentIdentityIndex,
) -> list[LegacyRun]:
    index_path = outputs / "_live" / "runs.jsonl"
    folded: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(_jsonl(index_path), start=1):
        run_id = row.get("run_id")
        if not run_id:
            raise MigrationError(f"{index_path}:{index}: run index row has no run_id")
        current = folded.setdefault(str(run_id), {"history": []})
        current["history"].append(row)
        if row.get("op") == "launched":
            current.update(row)
            current["terminal"] = False
        elif row.get("op") == "terminal":
            current.update(row)
            current["terminal"] = True

    physical: dict[str, Path] = {}
    if outputs.exists():
        for run_dir in sorted(
            path for path in outputs.glob("*/runs/*") if path.is_dir()
        ):
            if run_dir.is_symlink():
                raise MigrationError(
                    f"legacy run directory may not be a symlink: {run_dir}"
                )
            resolved_run_dir = run_dir.resolve()
            try:
                relative_parts = resolved_run_dir.relative_to(outputs.resolve()).parts
            except ValueError as exc:
                raise MigrationError(
                    f"legacy run directory points outside outputs/: {run_dir}"
                ) from exc
            if len(relative_parts) != 3 or relative_parts[1] != "runs":
                raise MigrationError(f"non-canonical legacy run directory: {run_dir}")
            meta = _json(run_dir / "meta.json", {})
            if not isinstance(meta, dict):
                raise MigrationError(f"{run_dir / 'meta.json'} must contain an object")
            if meta.get("run_id") is not None and str(meta["run_id"]) != run_dir.name:
                raise MigrationError(
                    f"legacy meta run_id {meta['run_id']!r} does not match "
                    f"directory {run_dir.name!r}"
                )
            run_id = str(meta.get("run_id") or run_dir.name)
            previous = physical.get(run_id)
            if previous is not None and previous.resolve() != run_dir.resolve():
                raise MigrationError(
                    f"legacy run id {run_id!r} appears in both {previous} and {run_dir}"
                )
            physical[run_id] = resolved_run_dir
            current = folded.setdefault(run_id, {"history": [], "terminal": False})
            current.setdefault("run_id", run_id)
            current.setdefault("dir", str(run_dir))

    runs: list[LegacyRun] = []
    for run_id, raw in sorted(folded.items()):
        raw_dir = raw.get("dir")
        run_dir = physical.get(run_id)
        if run_dir is not None and raw_dir:
            indexed = Path(str(raw_dir)).expanduser()
            if not indexed.is_absolute():
                indexed = workspace / indexed
            if indexed.resolve() != run_dir:
                raise MigrationError(
                    f"legacy run {run_id} index path {indexed.resolve()} does not "
                    f"match physical directory {run_dir}"
                )
        if run_dir is None and raw_dir:
            candidate = Path(str(raw_dir)).expanduser()
            if not candidate.is_absolute():
                candidate = workspace / candidate
            candidate = candidate.resolve()
            try:
                relative_parts = candidate.relative_to(outputs.resolve()).parts
            except ValueError as exc:
                raise MigrationError(
                    f"legacy run {run_id} points outside outputs/: {candidate}"
                ) from exc
            if (
                len(relative_parts) != 3
                or relative_parts[1] != "runs"
                or relative_parts[2] != run_id
            ):
                raise MigrationError(
                    f"legacy run {run_id} has non-canonical source path: {candidate}"
                )
            run_dir = candidate
        meta = _json(run_dir / "meta.json", {}) if run_dir is not None else {}
        status = _json(run_dir / "status.json", {}) if run_dir is not None else {}
        if not isinstance(meta, dict):
            raise MigrationError(f"{run_dir / 'meta.json'} must contain an object")
        if not isinstance(status, dict):
            raise MigrationError(f"{run_dir / 'status.json'} must contain an object")
        _one_value(
            label="run id",
            run_id=run_id,
            values=(run_id, meta.get("run_id"), status.get("run_id")),
        )
        raw_status = (
            status.get("status")
            or raw.get("final_status")
            or ("COMPLETED" if raw.get("terminal") else "RUNNING")
        )
        canonical_status = _canonical_run_status(raw_status)
        path_package = (
            run_dir.parents[1].name
            if run_dir is not None
            else None
        )
        package_id = _one_value(
            label="package id",
            run_id=run_id,
            values=(
                path_package,
                raw.get("pkg"),
                raw.get("package_id"),
                meta.get("pkg"),
                meta.get("package_id"),
                status.get("pkg"),
                status.get("package_id"),
            ),
        )
        local_experiment_id = _one_value(
            label="experiment id",
            run_id=run_id,
            values=(
                raw.get("experiment_local_id"),
                raw.get("exp_id"),
                meta.get("experiment_local_id"),
                meta.get("exp_id"),
                status.get("experiment_local_id"),
                status.get("exp_id"),
            ),
        )
        explicit_experiment_id = _one_value(
            label="canonical experiment id",
            run_id=run_id,
            values=(
                raw.get("experiment_id"),
                meta.get("experiment_id"),
                status.get("experiment_id"),
            ),
        )
        canonical_experiment_id: str | None = None
        experiment_identity_error: str | None = None
        if package_id and (
            local_experiment_id is not None
            or explicit_experiment_id is not None
        ):
            try:
                canonical_experiment_id = experiment_identities.resolve(
                    package_id,
                    local_experiment_id,
                    explicit_experiment_id,
                )
                if (
                    canonical_experiment_id is not None
                    and local_experiment_id is None
                ):
                    local_experiment_id = experiment_identities.local_id(
                        package_id,
                        canonical_experiment_id,
                    )
            except MigrationError as exc:
                experiment_identity_error = str(exc)
        runs.append(
            LegacyRun(
                run_id=run_id,
                package_id=package_id,
                experiment_local_id=local_experiment_id,
                canonical_experiment_id=canonical_experiment_id,
                experiment_identity_error=experiment_identity_error,
                status=canonical_status,
                source_dir=run_dir,
                meta=copy.deepcopy(meta),
                status_record=copy.deepcopy(status),
                history=tuple(copy.deepcopy(raw.get("history", []))),
            )
        )
    return runs


def _run_records(
    outputs: Path,
    workspace: Path,
    experiment_identities: ExperimentIdentityIndex,
    paths: ResearchPaths | None = None,
) -> Iterator[LegacyRecord]:
    paths = paths or ResearchPaths.resolve(workspace=workspace)
    for run in _discover_legacy_runs(
        outputs,
        workspace,
        experiment_identities=experiment_identities,
    ):
        if (
            run.source_dir is None
            or not run.package_id
            or not run.experiment_local_id
            or not run.experiment_id
            or not (run.source_dir / "meta.json").is_file()
        ):
            # The inventory carries a precise blocker. Do not create a guessed
            # or schema-invalid Run aggregate while the workspace is blocked.
            continue
        source_entries = _tree_manifest(run.source_dir)
        contract = _legacy_run_contract(paths, run, source_entries)
        yield contract["authorization"]
        if run.terminal:
            yield LegacyRecord(
                "RunLaunched",
                "run",
                run.run_id,
                {
                    "started_at": contract["started_at"],
                    "pid": run.status_record.get("pid") or run.meta.get("pid"),
                    "transport": contract["run_json"]["transport"],
                    "run_json": contract["run_json"]["run_json"],
                    "context_json": contract["run_json"]["context_json"],
                },
                contract["source"],
                f"run:{run.run_id}:launched",
            )
            yield LegacyRecord(
                "RunTerminal",
                "run",
                run.run_id,
                {
                    "status": run.status,
                    "ended_at": contract["ended_at"],
                    "exit_code": run.status_record.get("exit_code"),
                    "result_json": contract["run_json"]["result_json"],
                    "legacy_history": list(run.history),
                },
                contract["source"],
                f"run:{run.run_id}:terminal:{run.status}",
            )
            result = contract["result_json"]
            result_sha256 = _json_document_sha256(result)
            evidence = copy.deepcopy(result.get("evidence") or [])
            yield LegacyRecord(
                "RunResultFinalized",
                "run",
                run.run_id,
                {
                    "run_id": run.run_id,
                    "package_id": run.package_id,
                    "experiment_id": run.experiment_id,
                    "kind": "experiment-result",
                    "result_json": contract["run_json"]["result_json"],
                    "result_sha256": result_sha256,
                    "protocol": copy.deepcopy(result["protocol"]),
                    "measurements": copy.deepcopy(result["measurements"]),
                    "verdict": result["verdict"],
                    "validity": result["validity"],
                    "supported_claims": copy.deepcopy(
                        result["supported_claims"]
                    ),
                    "unsupported_claims": copy.deepcopy(
                        result["unsupported_claims"]
                    ),
                    "decision_candidate": copy.deepcopy(
                        result.get("decision_candidate")
                    ),
                    "evidence": evidence,
                    "evidence_count": len(evidence),
                },
                contract["source"],
                f"run:{run.run_id}:result:{result_sha256}",
            )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_manifest(root: Path) -> list[dict[str, Any]]:
    if not root.exists() or not root.is_dir():
        raise MigrationError(f"migration source directory is missing: {root}")
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            target = os.readlink(path)
            entries.append(
                {
                    "path": relative,
                    "type": "symlink",
                    "target": target,
                    "sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
                }
            )
        elif path.is_dir():
            entries.append({"path": relative, "type": "directory"})
        elif path.is_file():
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
        else:
            raise MigrationError(f"unsupported legacy run entry: {path}")
    return entries


def _manifest_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _first_value(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _started_at(run: LegacyRun) -> float:
    value = _first_value(
        run.meta.get("created_at_unix"),
        run.meta.get("started_at"),
        run.status_record.get("started_at"),
        next(
            (
                row.get("started_at")
                for row in run.history
                if row.get("started_at") is not None
            ),
            None,
        ),
        0.0,
    )
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise MigrationError(
            f"legacy run {run.run_id} has non-numeric started_at {value!r}"
        ) from exc


def _ended_at(run: LegacyRun, started_at: float) -> float:
    value = _first_value(
        run.status_record.get("ended_at"),
        next(
            (
                row.get("ended_at")
                for row in reversed(run.history)
                if row.get("ended_at") is not None
            ),
            None,
        ),
        started_at,
    )
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise MigrationError(
            f"legacy run {run.run_id} has non-numeric ended_at {value!r}"
        ) from exc


def _iso_time(timestamp: float) -> str:
    return dt.datetime.fromtimestamp(timestamp, dt.UTC).isoformat(
        timespec="milliseconds"
    )


def _legacy_context(
    paths: ResearchPaths,
    run: LegacyRun,
    *,
    captured_at: float,
) -> dict[str, Any]:
    from lib.experiments.contracts import context_sha256

    assert run.package_id is not None
    assert run.experiment_id is not None
    assert run.experiment_local_id is not None
    assert run.source_dir is not None
    package_root = paths.workspace / LEGACY_OUTPUTS / run.package_id
    context_path = package_root / "context_pack.json"
    context_md_path = package_root / "context_pack.md"
    legacy_context: dict[str, Any] = {}
    if context_path.exists():
        legacy_context["json"] = _json(context_path)
        legacy_context["json_sha256"] = _sha256_file(context_path)
    if context_md_path.exists():
        legacy_context["markdown"] = context_md_path.read_text(encoding="utf-8")
        legacy_context["markdown_sha256"] = _sha256_file(context_md_path)
    snapshot = {
        "schema_version": 1,
        "captured_at": _iso_time(captured_at),
        "source_seq": None,
        "source_hash": None,
        "data": {
            "legacy_context_pack": legacy_context,
            "migration": {
                "source_run": _relative(run.source_dir, paths.workspace),
                "meta_sha256": _sha256_file(run.source_dir / "meta.json"),
            },
        },
        "selected_experiment_id": run.experiment_id,
        "selected_experiment_local_id": run.experiment_local_id,
    }
    snapshot["context_sha256"] = context_sha256(snapshot)
    return snapshot


def _legacy_result(run: LegacyRun, *, ended_at: float) -> dict[str, Any]:
    assert run.source_dir is not None
    existing_path = run.source_dir / "result.json"
    existing = _json(existing_path, {})
    if not isinstance(existing, dict):
        raise MigrationError(f"{existing_path}: result must be a JSON object")
    verdict = existing.get("verdict")
    if verdict not in enum("result_verdict"):
        verdict = "INCONCLUSIVE"
    validity = existing.get("validity")
    if validity not in enum("result_validity"):
        validity = "UNMEASURED"
    protocol = existing.get("protocol")
    if not isinstance(protocol, dict):
        protocol = {
            "kind": "legacy-migration",
            "source": _relative(run.source_dir, run.source_dir.parents[3]),
        }
    measurements = existing.get("measurements")
    if not isinstance(measurements, dict):
        measurements = {}
    decision_candidate = existing.get("decision_candidate")
    if decision_candidate is not None and not isinstance(decision_candidate, dict):
        decision_candidate = None

    def claims(name: str) -> list[str]:
        value = existing.get(name)
        if not isinstance(value, list):
            return []
        return [
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        ]

    result: dict[str, Any] = {
        "schema_version": 1,
        "kind": "experiment-result",
        "run_id": run.run_id,
        "package_id": run.package_id,
        "experiment_id": run.experiment_id,
        "status": run.status,
        "exit_code": run.status_record.get("exit_code"),
        "ended_at": ended_at,
        "protocol": copy.deepcopy(protocol),
        "measurements": copy.deepcopy(measurements),
        "verdict": verdict,
        "validity": validity,
        "supported_claims": claims("supported_claims"),
        "unsupported_claims": claims("unsupported_claims"),
        "decision_candidate": copy.deepcopy(decision_candidate),
        # Legacy references point outside the new run hierarchy and therefore
        # cannot be promoted to EvidenceRefs without falsifying provenance.
        "evidence": [],
    }
    if existing:
        result["legacy"] = {
            "result": copy.deepcopy(existing),
            "sha256": _sha256_file(existing_path),
        }
    return result


def _legacy_status(
    run: LegacyRun,
    *,
    started_at: float,
    ended_at: float,
) -> dict[str, Any]:
    status = {
        "schema_version": 1,
        "run_id": run.run_id,
        "package_id": run.package_id,
        "experiment_id": run.experiment_id,
        "experiment_local_id": run.experiment_local_id,
        "status": run.status,
        "started_at": started_at,
        "ended_at": ended_at,
        "exit_code": run.status_record.get("exit_code"),
        "pid": run.status_record.get("pid") or run.meta.get("pid"),
        "launch_failed": False,
        "health": {"state": "TERMINAL", "reasons": []},
        "legacy": copy.deepcopy(run.status_record),
    }
    return status


def _legacy_run_contract(
    paths: ResearchPaths,
    run: LegacyRun,
    source_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    from lib.experiments.contracts import launch_sha256

    if run.source_dir is None:
        raise MigrationError(f"legacy run {run.run_id} has no source directory")
    if not run.package_id or not run.experiment_local_id or not run.experiment_id:
        raise MigrationError(
            f"legacy run {run.run_id} has no explicit package/experiment identity"
        )
    meta_path = run.source_dir / "meta.json"
    if not meta_path.is_file():
        raise MigrationError(f"terminal legacy run has no meta.json: {meta_path}")
    meta_entry = next(
        (
            entry
            for entry in source_entries
            if entry["path"] == "meta.json" and entry["type"] == "file"
        ),
        None,
    )
    if meta_entry is None:
        raise MigrationError(f"terminal legacy run has invalid meta.json: {meta_path}")
    destination = paths.run_dir(
        run.package_id,
        run.experiment_local_id,
        run.run_id,
    )
    destination_relative = _relative(destination, paths.root)
    started_at = _started_at(run)
    ended_at = _ended_at(run, started_at)
    context = _legacy_context(paths, run, captured_at=started_at)
    command = run.meta.get("command")
    if command is None:
        command = next(
            (
                row.get("command")
                for row in run.history
                if row.get("command") is not None
            ),
            [],
        )
    if isinstance(command, str):
        command = [command]
    if not isinstance(command, list) or not all(
        isinstance(value, str) for value in command
    ):
        raise MigrationError(f"legacy run {run.run_id} command must be a string array")
    environment = run.meta.get("environment")
    if not isinstance(environment, dict):
        environment = {
            "sha256": str(run.meta.get("env_digest") or ""),
            "keys": {},
        }
    resource = run.meta.get("resource")
    if not isinstance(resource, dict):
        resource = {
            key: copy.deepcopy(run.meta[key])
            for key in ("server", "alloc_id")
            if run.meta.get(key) is not None
        }
    launch_spec: dict[str, Any] = {
        "run_id": run.run_id,
        "package_id": run.package_id,
        "experiment_id": run.experiment_id,
        "experiment_local_id": run.experiment_local_id,
        "command": copy.deepcopy(command),
        "cwd": str(run.meta.get("cwd") or paths.workspace),
        "created_at": str(run.meta.get("created_at") or _iso_time(started_at)),
        "created_at_unix": started_at,
        "context_source_seq": context.get("source_seq"),
        "context_source_hash": context.get("source_hash"),
        "context_sha256": context["context_sha256"],
        "run_json": f"{destination_relative}/run.json",
        "context_json": f"{destination_relative}/context.json",
        "result_json": f"{destination_relative}/result.json",
        "log_path": f"{destination_relative}/log.txt",
        "events_path": f"{destination_relative}/events.jsonl",
        "metrics_path": f"{destination_relative}/metrics.jsonl",
        "environment": copy.deepcopy(environment),
        "gpu_ids": list(run.meta.get("gpu_ids") or []),
        "git_commit": run.meta.get("git_commit"),
        "transport": str(run.meta.get("transport") or "legacy-migrated"),
        "tmux_session": run.meta.get("tmux_session"),
        "heartbeat_timeout": int(run.meta.get("heartbeat_timeout") or 600),
        "total_steps": run.meta.get("total_steps"),
        "metrics_regexes": list(run.meta.get("metrics_regexes") or []),
        "gpu_sample": bool(run.meta.get("gpu_sample", False)),
        "retry_of": run.meta.get("retry_of"),
        "resource": copy.deepcopy(resource),
        "launch_ack_decision_id": run.meta.get("launch_ack_decision_id"),
        "telemetry": copy.deepcopy(run.meta.get("telemetry") or {}),
        "expected_duration_class": run.meta.get("expected_duration_class"),
        "log_adapter": str(run.meta.get("log_adapter") or "legacy"),
    }
    launch_digest = launch_sha256(launch_spec)
    state_record: dict[str, Any] = {
        "id": run.run_id,
        "run_id": run.run_id,
        "package_id": run.package_id,
        "experiment_id": run.experiment_id,
        "experiment_local_id": run.experiment_local_id,
        "status": "QUEUED",
        "dir": destination_relative,
        "run_json": launch_spec["run_json"],
        "context_json": launch_spec["context_json"],
        "context_source_seq": launch_spec["context_source_seq"],
        "context_source_hash": launch_spec["context_source_hash"],
        "context_sha256": context["context_sha256"],
        "launch_sha256": launch_digest,
        "requested_at": started_at,
        "retry_of": launch_spec["retry_of"],
        "resource": copy.deepcopy(resource),
        "launch_ack_decision_id": launch_spec["launch_ack_decision_id"],
        "transport": launch_spec["transport"],
        "legacy_path": _relative(run.source_dir, paths.workspace),
        "legacy_meta": copy.deepcopy(run.meta),
    }
    source = _relative(run.source_dir, paths.workspace)
    authorization = LegacyRecord(
        "RunLaunchAuthorized",
        "run",
        run.run_id,
        state_record,
        source,
        f"run:{run.run_id}:authorization",
    )
    run_json: dict[str, Any] = {
        "schema_version": 1,
        "authorization_event_id": f"evt_legacy_{authorization.digest[:24]}",
        "launch_sha256": launch_digest,
        **launch_spec,
        "legacy_path": source,
        "legacy": {
            "meta": copy.deepcopy(run.meta),
            "meta_sha256": meta_entry["sha256"],
            "source_tree_sha256": _manifest_sha256(source_entries),
            "source_files": copy.deepcopy(source_entries),
        },
    }
    contract = {
        "authorization": authorization,
        "source": source,
        "started_at": started_at,
        "ended_at": ended_at,
        "run_json": run_json,
        "context_json": context,
    }
    if run.terminal:
        contract["status_json"] = _legacy_status(
            run,
            started_at=started_at,
            ended_at=ended_at,
        )
        contract["result_json"] = _legacy_result(run, ended_at=ended_at)
    return contract


def _json_document_sha256(value: Any) -> str:
    encoded = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_destination(
    destination: Path,
    *,
    expected_documents: dict[str, dict[str, Any]],
    source_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    for name, expected in expected_documents.items():
        path = destination / name
        if not path.is_file():
            raise MigrationError(f"migrated run is missing canonical {name}: {path}")
        try:
            actual = read_json(path)
        except json.JSONDecodeError as exc:
            raise MigrationError(f"malformed migrated {name} {path}: {exc}") from exc
        if actual != expected or _sha256_file(path) != _json_document_sha256(expected):
            raise MigrationError(f"migrated {name} drift detected: {path}")

    reserved = {"meta.json", *expected_documents}
    expected_payload = [
        entry
        for entry in source_entries
        if entry["path"] not in reserved
    ]
    destination_entries = _tree_manifest(destination)
    actual_payload = [
        entry for entry in destination_entries if entry["path"] not in expected_documents
    ]
    if actual_payload != expected_payload:
        raise MigrationError(
            f"migrated run file drift detected between source and {destination}"
        )
    return destination_entries


def _copy_terminal_run(
    paths: ResearchPaths,
    run: LegacyRun,
) -> dict[str, Any]:
    assert run.source_dir is not None
    assert run.package_id is not None
    assert run.experiment_local_id is not None
    source_entries = _tree_manifest(run.source_dir)
    if any(entry["path"] == "run.json" for entry in source_entries):
        raise MigrationError(
            f"legacy run already contains run.json and cannot be transformed safely: "
            f"{run.source_dir}"
        )
    contract = _legacy_run_contract(paths, run, source_entries)
    expected_documents = {
        "run.json": contract["run_json"],
        "context.json": contract["context_json"],
        "status.json": contract["status_json"],
        "result.json": contract["result_json"],
    }
    destination = paths.run_dir(
        run.package_id,
        run.experiment_local_id,
        run.run_id,
    )
    if destination.is_symlink():
        raise MigrationError(
            f"migrated run destination may not be a symlink: {destination}"
        )
    for ancestor in (
        paths.experiments / run.package_id,
        paths.experiments / run.package_id / run.experiment_local_id,
    ):
        if ancestor.is_symlink():
            raise MigrationError(
                f"migrated run destination parent may not be a symlink: {ancestor}"
            )
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.parent.resolve().relative_to(paths.experiments.resolve())
    except ValueError as exc:
        raise MigrationError(
            f"migrated run destination escapes experiments root: {destination}"
        ) from exc
    copied = False
    if destination.exists():
        destination_entries = _verify_destination(
            destination,
            expected_documents=expected_documents,
            source_entries=source_entries,
        )
    else:
        staging = destination.parent / (
            f".{destination.name}.migration-{uuid.uuid4().hex}"
        )
        try:
            shutil.copytree(run.source_dir, staging, symlinks=True)
            for reserved in ("meta.json", *expected_documents):
                (staging / reserved).unlink(missing_ok=True)
            for name, document in expected_documents.items():
                write_json_atomic(staging / name, document)
            # Atomic publication means a crash cannot expose a half-copied run.
            os.rename(staging, destination)
            directory_fd = os.open(destination.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            copied = True
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        destination_entries = _verify_destination(
            destination,
            expected_documents=expected_documents,
            source_entries=source_entries,
        )
    return {
        "run_id": run.run_id,
        "package_id": run.package_id,
        "experiment_id": run.experiment_id,
        "experiment_local_id": run.experiment_local_id,
        "status": run.status,
        "source_path": _relative(run.source_dir, paths.workspace),
        "destination_path": _relative(destination, paths.workspace),
        "source_tree_sha256": _manifest_sha256(source_entries),
        "source_files": source_entries,
        "run_json_sha256": _sha256_file(destination / "run.json"),
        "context_json_sha256": _sha256_file(destination / "context.json"),
        "status_json_sha256": _sha256_file(destination / "status.json"),
        "result_json_sha256": _sha256_file(destination / "result.json"),
        "destination_tree_sha256": _manifest_sha256(destination_entries),
        "copied": copied,
    }


def _run_blockers(paths: ResearchPaths, runs: list[LegacyRun]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for run in runs:
        source = (
            _relative(run.source_dir, paths.workspace)
            if run.source_dir is not None
            else None
        )
        if run.status in ACTIVE_RUN_STATUSES:
            blockers.append(
                {
                    "code": "ACTIVE_LEGACY_RUN",
                    "run_id": run.run_id,
                    "status": run.status,
                    "source_path": source,
                    "disposition": "deferred-until-terminal",
                }
            )
        elif run.status not in TERMINAL_RUN_STATUSES:
            blockers.append(
                {
                    "code": "UNKNOWN_LEGACY_RUN_STATUS",
                    "run_id": run.run_id,
                    "status": run.status,
                    "source_path": source,
                }
            )
        if not run.package_id:
            blockers.append(
                {
                    "code": "MISSING_PACKAGE_ID",
                    "run_id": run.run_id,
                    "source_path": source,
                }
            )
        if not run.experiment_local_id:
            blockers.append(
                {
                    "code": "MISSING_EXPERIMENT_ID",
                    "run_id": run.run_id,
                    "source_path": source,
                    "detail": "migration will not infer an experiment from package order",
                }
            )
        elif run.experiment_identity_error:
            blockers.append(
                {
                    "code": "UNKNOWN_EXPERIMENT_ID",
                    "run_id": run.run_id,
                    "source_path": source,
                    "detail": run.experiment_identity_error,
                }
            )
        elif not run.experiment_id:
            blockers.append(
                {
                    "code": "MISSING_CANONICAL_EXPERIMENT_ID",
                    "run_id": run.run_id,
                    "source_path": source,
                }
            )
        if run.source_dir is None or not run.source_dir.is_dir():
            blockers.append(
                {
                    "code": "MISSING_RUN_DIRECTORY",
                    "run_id": run.run_id,
                    "source_path": source,
                }
            )
        elif run.terminal and not (run.source_dir / "meta.json").is_file():
            blockers.append(
                {
                    "code": "MISSING_META_JSON",
                    "run_id": run.run_id,
                    "source_path": source,
                }
            )
        if run.package_id and run.experiment_local_id:
            try:
                paths.run_dir(
                    run.package_id,
                    run.experiment_local_id,
                    run.run_id,
                )
            except ValueError as exc:
                blockers.append(
                    {
                        "code": "UNSAFE_RUN_IDENTITY",
                        "run_id": run.run_id,
                        "source_path": source,
                        "detail": str(exc),
                    }
                )
    return blockers


def _authority_source_paths(
    workspace: Path,
    runs: list[LegacyRun],
) -> list[Path]:
    del runs
    candidates: set[Path] = set()
    for root_name in (LEGACY_INTERFACE, LEGACY_OUTPUTS):
        root = workspace / root_name
        if not root.exists():
            continue
        candidates.update(
            path
            for path in root.rglob("*")
            if path.is_file() or path.is_symlink()
        )
    return sorted(candidates, key=lambda path: _relative(path, workspace))


def _classification(
    path: Path,
    workspace: Path,
) -> tuple[str, str, dict[str, Any] | None]:
    """Assign one explicit disposition to every legacy file."""
    relative = path.relative_to(workspace)
    parts = relative.parts
    blocker: dict[str, Any] | None = None

    if path.is_symlink():
        return (
            "unsafe-symlink",
            "blocked",
            {
                "code": "LEGACY_AUTHORITY_SYMLINK",
                "path": relative.as_posix(),
            },
        )

    if parts[0] == LEGACY_INTERFACE:
        tail = parts[1:]
        if tail[:2] == ("data", "packages"):
            if path.name.endswith(".facts.js") or path.suffix.lower() in {
                ".csv",
                ".json",
                ".jsonl",
            }:
                return (
                    "package-fact-authority",
                    "archived-as-raw-provenance",
                    None,
                )
            blocker = {
                "code": "UNSUPPORTED_LEGACY_FACT",
                "path": relative.as_posix(),
            }
            return "package-fact-authority", "blocked", blocker
        if tail[:1] == ("data",):
            known_authority = {
                "research-packages.js",
                "brainstorms.js",
                "rules.js",
                "papers.jsonl",
                "edges.jsonl",
                "gaps.jsonl",
            }
            if len(tail) == 2 and tail[1] in known_authority:
                return "interface-data-authority", "imported-to-state", None
            known_projection_prefixes = (
                "schema",
                "scope",
                "self-evolution",
                "live",
            )
            if len(tail) == 2 and tail[1].startswith(known_projection_prefixes):
                return "interface-data-projection", "rebuildable", None
            return (
                "unclassified-interface-data",
                "blocked",
                {
                    "code": "UNCLASSIFIED_LEGACY_AUTHORITY",
                    "path": relative.as_posix(),
                    "detail": "unknown research_html/data file may contain authority",
                },
            )
        if tail[:1] == ("packages",) and path.suffix.lower() in {
            ".html",
            ".md",
            ".txt",
        }:
            return "package-human-content", "imported-as-note", None
        if tail[:1] == ("brainstorm",) and path.suffix.lower() == ".html":
            return "brainstorm-human-content", "imported-as-note", None
        return "interface-projection", "rebuildable", None

    if parts[0] != LEGACY_OUTPUTS:
        return (
            "outside-legacy-roots",
            "blocked",
            {
                "code": "UNCLASSIFIED_LEGACY_AUTHORITY",
                "path": relative.as_posix(),
            },
        )

    tail = parts[1:]
    if not tail:
        return "legacy-output-root", "rebuildable", None
    head = tail[0]
    if head == "_scope":
        if tail[1:] in {
            ("transitions.jsonl",),
            ("triage.jsonl",),
            ("prior_knowledge.md",),
            ("memory.jsonl",),
        }:
            return "scope-authority", "imported-to-state", None
        return "scope-projection", "rebuildable", None
    if head == "_resources":
        if tail[1:] in {("servers.json",), ("allocations.jsonl",)}:
            return "resource-authority", "imported-to-state", None
        return "resource-probe-evidence", "retained-legacy-evidence", None
    if head == "_auto":
        if len(tail) == 3 and tail[2] == "campaign.jsonl":
            return "campaign-authority", "imported-to-state", None
        return "campaign-handoff", "retained-legacy-evidence", None
    if head == "_live":
        if tail[1:] in {("runs.jsonl",), ("acknowledged.json",)}:
            return "live-authority", "imported-to-state-and-run-store", None
        return "live-process-runtime", "ephemeral-not-imported", None
    if head == "_brainstorm":
        if len(tail) == 3 and tail[2] == "candidates.json":
            return "brainstorm-candidate-authority", "imported-to-state", None
        if len(tail) == 4 and tail[2] == "verdicts" and path.suffix == ".json":
            return "brainstorm-decision-authority", "imported-to-state", None
        return (
            "unclassified-brainstorm-authority",
            "blocked",
            {
                "code": "UNCLASSIFIED_LEGACY_AUTHORITY",
                "path": relative.as_posix(),
                "detail": "unknown _brainstorm file has no deterministic migration rule",
            },
        )
    if head == "_learned":
        if tail[1:] == ("rules.md",):
            return "learned-rule-authority", "imported-to-state", None
        return (
            "unclassified-learned-authority",
            "blocked",
            {
                "code": "UNCLASSIFIED_LEGACY_AUTHORITY",
                "path": relative.as_posix(),
                "detail": "unknown _learned file has no deterministic migration rule",
            },
        )
    if head == "_selfevolve":
        self_tail = tail[1:]
        known_state = (
            self_tail in {
                ("rules", "transitions.jsonl"),
                ("skills", "transitions.jsonl"),
                ("approvals", "approvals.jsonl"),
                ("events", "events.jsonl"),
            }
            or (
                len(self_tail) == 5
                and self_tail[0] == "rules"
                and self_tail[1] in {"candidates", "releases"}
                and self_tail[4] == "rule.json"
            )
            or (
                len(self_tail) >= 2
                and self_tail[0] == "evidence"
                and path.suffix == ".json"
            )
            or (
                len(self_tail) == 5
                and self_tail[0] == "skills"
                and self_tail[1] in {"candidates", "releases"}
                and self_tail[4] == "manifest.json"
            )
        )
        if known_state:
            return "selfevolve-authority", "imported-to-state", None
        if self_tail[:1] == ("projections",):
            return "selfevolve-projection", "rebuildable", None
        if self_tail[:2] in {
            ("rules", "releases"),
            ("skills", "releases"),
            ("skills", "candidates"),
        }:
            return "selfevolve-executable-bundle", "retained-inert-legacy-bundle", None
        if path.suffix.lower() in {".json", ".jsonl", ".md", ".txt", ".log"}:
            return "selfevolve-support-evidence", "imported-to-state", None
        return (
            "unclassified-selfevolve-authority",
            "blocked",
            {
                "code": "UNCLASSIFIED_LEGACY_AUTHORITY",
                "path": relative.as_posix(),
                "detail": "unknown _selfevolve file has no deterministic migration rule",
            },
        )
    if head.startswith("_"):
        return (
            "unknown-global-store",
            "blocked",
            {
                "code": "UNCLASSIFIED_LEGACY_AUTHORITY",
                "path": relative.as_posix(),
                "detail": f"unknown legacy global store {head}",
            },
        )

    if len(tail) >= 2 and tail[1] == "_actions.jsonl":
        return "package-audit-authority", "imported-to-audit", None
    if len(tail) == 2 and tail[1] in {"context_pack.md", "context_pack.json"}:
        return "context-pack-projection", "recomputed-per-run", None
    if len(tail) >= 2 and tail[1] == "manifests":
        if path.name.endswith(".applied"):
            return "consumed-package-manifest", "transport-receipt", None
        applied = Path(str(path) + ".applied").exists()
        if applied:
            return "consumed-package-manifest", "transport-already-applied", None
        return (
            "pending-package-manifest",
            "blocked",
            {
                "code": "PENDING_LEGACY_MANIFEST",
                "path": relative.as_posix(),
                "detail": "apply or explicitly discard the pending handoff before migration",
            },
        )
    if len(tail) >= 3 and tail[1] == "runs":
        return "run-evidence-authority", "copied-to-experiments", None
    return (
        "unclassified-package-output",
        "blocked",
        {
            "code": "UNCLASSIFIED_LEGACY_AUTHORITY",
            "path": relative.as_posix(),
            "detail": "package output is outside a typed Run and cannot be placed safely",
        },
    )


def _authority_inventory(
    workspace: Path,
    runs: list[LegacyRun],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for path in _authority_source_paths(workspace, runs):
        classification, disposition, blocker = _classification(path, workspace)
        relative = _relative(path, workspace)
        entries.append(
            {
                "path": relative,
                "classification": classification,
                "disposition": disposition,
            }
        )
        counts[classification] = counts.get(classification, 0) + 1
        if blocker is not None:
            blockers.append(blocker)
    family_prefixes = {
        "brainstorm": f"{LEGACY_OUTPUTS}/_brainstorm/",
        "learned": f"{LEGACY_OUTPUTS}/_learned/",
        "selfevolve": f"{LEGACY_OUTPUTS}/_selfevolve/",
        "package_facts": f"{LEGACY_INTERFACE}/data/packages/",
    }
    families: dict[str, dict[str, Any]] = {}
    for name, prefix in family_prefixes.items():
        matched = [entry for entry in entries if entry["path"].startswith(prefix)]
        families[name] = {
            "covered": True,
            "files": len(matched),
            "dispositions": sorted({entry["disposition"] for entry in matched}),
        }
    for name, predicate in (
        (
            "package_manifests",
            lambda value: value.startswith(f"{LEGACY_OUTPUTS}/")
            and "/manifests/" in value,
        ),
        (
            "context_packs",
            lambda value: value.startswith(f"{LEGACY_OUTPUTS}/")
            and value.endswith(("/context_pack.md", "/context_pack.json")),
        ),
    ):
        matched = [entry for entry in entries if predicate(entry["path"])]
        families[name] = {
            "covered": True,
            "files": len(matched),
            "dispositions": sorted({entry["disposition"] for entry in matched}),
        }
    return {
        "complete": not blockers,
        "files": entries,
        "by_classification": counts,
        "families": families,
        "unresolved": blockers,
    }


def _source_manifest(
    workspace: Path,
    runs: list[LegacyRun],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in _authority_source_paths(workspace, runs):
        _, disposition, _ = _classification(path, workspace)
        if disposition == "ephemeral-not-imported":
            continue
        relative = _relative(path, workspace)
        if path.is_symlink():
            target = os.readlink(path)
            entries.append(
                {
                    "path": relative,
                    "type": "symlink",
                    "target": target,
                    "sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
                }
            )
        else:
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    return {
        "files": entries,
        "sha256": _manifest_sha256(entries),
    }


def discover(
    workspace: Path,
    paths: ResearchPaths | None = None,
    *,
    _semantic_out: dict[str, Any] | None = None,
) -> list[LegacyRecord]:
    """Read every known legacy management store without modifying it."""
    workspace = workspace.resolve()
    interface = workspace / LEGACY_INTERFACE
    outputs = workspace / LEGACY_OUTPUTS
    records: list[LegacyRecord] = []

    scope_path = outputs / "_scope" / "transitions.jsonl"
    source = _relative(scope_path, workspace)
    scope_rows = _jsonl(scope_path)
    direction_versions = {
        str(node["id"]): int(node.get("version") or 1)
        for row in scope_rows
        if isinstance(row.get("node"), dict)
        for node in [row["node"]]
        if node.get("level") == "direction" and node.get("id")
    }
    scope_records: list[LegacyRecord] = []
    scope_histories: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(scope_rows, start=1):
        node = row.get("node")
        identity = (
            str(node.get("id"))
            if isinstance(node, dict) and node.get("id") is not None
            else f"invalid:{index}"
        )
        history = scope_histories.setdefault(identity, [])
        history.append(copy.deepcopy(row))
        scope_records.append(
            _scope_record(
                row,
                source,
                index,
                direction_versions=direction_versions,
                transition_history=history,
            )
        )
    records.extend(scope_records)
    scope_experiments = {
        item.aggregate_id: item
        for item in scope_records
        if item.aggregate_type == "experiment"
    }

    triage_path = outputs / "_scope" / "triage.jsonl"
    source = _relative(triage_path, workspace)
    records.extend(
        _proposal_record(row, source, index)
        for index, row in enumerate(_jsonl(triage_path), start=1)
    )

    package_records = list(
        _package_records(
            interface / "data" / "research-packages.js",
            workspace,
            scope_experiments=scope_experiments,
            direction_versions=direction_versions,
        )
        or []
    )
    records.extend(package_records)
    experiment_identities = _experiment_identity_index(records)
    known_packages = {
        item.aggregate_id
        for item in package_records
        if item.aggregate_type == "package"
    }
    records.extend(
        _global_records(
            interface / "data" / "brainstorms.js",
            "BRAINSTORMS",
            "brainstorm",
            workspace,
        )
        or []
    )
    records.extend(
        _global_records(
            interface / "data" / "rules.js",
            "RESEARCH_RULES",
            "rule",
            workspace,
        )
        or []
    )
    for name, aggregate_type in (
        ("papers.jsonl", "paper"),
        ("edges.jsonl", "knowledge_edge"),
        ("gaps.jsonl", "knowledge_gap"),
    ):
        records.extend(
            _knowledge_records(interface / "data" / name, aggregate_type, workspace)
            or []
        )
    records.extend(
        _package_fact_records(
            interface / "data" / "packages",
            workspace,
            known_packages=known_packages,
        )
        or []
    )
    records.extend(_brainstorm_aux_records(outputs, workspace) or [])
    records.extend(_learned_rule_records(outputs, workspace) or [])
    records.extend(_selfevolve_records(outputs, workspace) or [])
    records.extend(
        _resource_records(
            outputs,
            workspace,
            experiment_identities=experiment_identities,
        )
        or []
    )
    records.extend(_campaign_records(outputs, workspace) or [])
    records.extend(
        _run_records(
            outputs,
            workspace,
            experiment_identities,
            paths,
        )
        or []
    )
    legacy_runs = _discover_legacy_runs(
        outputs,
        workspace,
        experiment_identities=experiment_identities,
    )
    semantic = _semantic_fact_analysis(
        records,
        workspace=workspace,
        identities=experiment_identities,
        runs=legacy_runs,
    )
    if _semantic_out is not None:
        _semantic_out.update(
            {
                "ledger": copy.deepcopy(list(semantic.ledger)),
                "blockers": copy.deepcopy(list(semantic.blockers)),
                "gate": semantic.gate(),
            }
        )
    return list(semantic.records)


def _page_notes(workspace: Path, store: EventStore) -> Iterator[LegacyRecord]:
    packages_root = workspace / LEGACY_INTERFACE / "packages"
    if not packages_root.exists():
        return
    for package_dir in sorted(path for path in packages_root.iterdir() if path.is_dir()):
        notes: dict[str, dict[str, Any]] = {}
        for path in sorted(package_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".html", ".md", ".txt"}:
                continue
            relative = path.relative_to(package_dir).as_posix()
            mime = "text/html" if path.suffix.lower() == ".html" else "text/markdown"
            notes[relative] = store.write_note(
                path.read_bytes(),
                mime=mime,
                title=f"{package_dir.name}/{relative}",
            )
        if notes:
            yield LegacyRecord(
                "AggregatePatched",
                "package",
                package_dir.name,
                {"interface_notes": notes},
                _relative(package_dir, workspace),
                f"pages:{package_dir.name}",
            )


def _brainstorm_page_notes(
    workspace: Path,
    store: EventStore,
) -> Iterator[LegacyRecord]:
    """Lift editable brainstorm detail pages into NoteRefs before interface cutover."""
    legacy_root = workspace / LEGACY_INTERFACE
    page_root = legacy_root / "brainstorm"
    if not page_root.exists():
        return
    brainstorms = store.state()["aggregates"]["brainstorm"]
    by_detail = {
        str(record.get("detailPath", "")).lstrip("./"): brainstorm_id
        for brainstorm_id, record in brainstorms.items()
        if record.get("detailPath")
    }
    for path in sorted(page_root.glob("*.html")):
        relative = path.relative_to(legacy_root).as_posix()
        brainstorm_id = by_detail.get(relative)
        if brainstorm_id is None:
            suffix_matches = [
                candidate
                for candidate in brainstorms
                if path.name.endswith(f"-{candidate}.html")
            ]
            if len(suffix_matches) == 1:
                brainstorm_id = suffix_matches[0]
        if brainstorm_id is None:
            digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
            brainstorm_id = f"legacy-brainstorm-{digest}"
            yield LegacyRecord(
                "AggregateImported",
                "brainstorm",
                brainstorm_id,
                {
                    "id": brainstorm_id,
                    "title": path.stem,
                    "status": "LEGACY_DETAIL_ONLY",
                    "legacy_detail_path": relative,
                },
                _relative(path, workspace),
                f"placeholder:{relative}",
            )
        note = store.write_note(
            path.read_bytes(),
            mime="text/html",
            title=f"Imported brainstorm detail {relative}",
        )
        yield LegacyRecord(
            "AggregatePatched",
            "brainstorm",
            str(brainstorm_id),
            {
                "detail_note": note,
                "legacy_detail_path": relative,
            },
            _relative(path, workspace),
            f"detail-page:{relative}",
        )


def _commit_legacy(store: EventStore, item: LegacyRecord) -> bool:
    digest = item.digest
    before = len(store.events())
    causation_id: str | None = None
    if item.event_type == "AggregatePatched":
        payload = {"patch": item.record, "_migration": item.payload["_migration"]}
    elif item.event_type == "RunLaunched":
        payload = {"patch": item.record, "_migration": item.payload["_migration"]}
        authorization = next(
            (
                event
                for event in reversed(store.events())
                if event["aggregate_type"] == "run"
                and event["aggregate_id"] == item.aggregate_id
                and event["event_type"] == "RunLaunchAuthorized"
            ),
            None,
        )
        causation_id = (
            str(authorization["event_id"])
            if authorization is not None
            else None
        )
    elif item.event_type == "RunTerminal":
        current = store.state()["aggregates"]["run"].get(item.aggregate_id)
        if isinstance(current, dict):
            causation_id = current.get("launched_event_id")
        payload = {
            "status": item.record["status"],
            "patch": {
                key: copy.deepcopy(value)
                for key, value in item.record.items()
                if key != "status"
            },
            "_migration": item.payload["_migration"],
        }
    elif item.event_type == "RunResultFinalized":
        current = store.state()["aggregates"]["run"].get(item.aggregate_id)
        if isinstance(current, dict):
            causation_id = current.get("terminal_event_id")
        payload = {
            "result": copy.deepcopy(item.record),
            "_migration": item.payload["_migration"],
        }
    elif item.event_type == "RunAttentionAcknowledged":
        payload = {**item.record, "_migration": item.payload["_migration"]}
    else:
        payload = item.payload
    store.commit(
        event_type=item.event_type,
        aggregate_type=item.aggregate_type,
        aggregate_id=item.aggregate_id,
        payload=payload,
        actor=ACTOR,
        idempotency_key=f"legacy:{digest}",
        event_id=f"evt_legacy_{digest[:24]}",
        command_id=f"cmd_legacy_{digest[:24]}",
        causation_id=causation_id,
        entry_skill="research-migrate",
    )
    return len(store.events()) > before


def _migrate_attention(workspace: Path, store: EventStore) -> int:
    path = workspace / LEGACY_OUTPUTS / "_live" / "acknowledged.json"
    data = _json(path, {})
    if not data:
        return 0
    if not isinstance(data, dict):
        raise MigrationError(f"{path}: acknowledged store must be an object")
    count = 0
    for run_id, value in sorted(data.items()):
        if run_id not in store.state()["aggregates"]["run"]:
            continue
        item = LegacyRecord(
            "RunAttentionAcknowledged",
            "run",
            str(run_id),
            {"patch": {"legacy_attention": value}},
            _relative(path, workspace),
            str(run_id),
        )
        count += int(_commit_legacy(store, item))
    return count


def _migrate_legacy_audit(workspace: Path, paths: ResearchPaths) -> int:
    added = 0
    outputs = workspace / LEGACY_OUTPUTS
    if not outputs.exists():
        return 0
    store = EventStore(paths, migration_mode=True)
    for path in sorted(outputs.glob("*/_actions.jsonl")):
        for index, row in enumerate(_jsonl(path), start=1):
            added += int(
                store.import_legacy_audit(
                    row,
                    source=_relative(path, workspace),
                    source_line=index,
                )
            )
    return added


def _import_parity(
    paths: ResearchPaths,
    records: list[LegacyRecord],
    *,
    migration_mode: bool,
    legacy_sources_archived: bool = False,
) -> dict[str, Any]:
    store = EventStore(paths, migration_mode=migration_mode)
    # Folding verifies schema versions, sequence numbers, aggregate versions,
    # the hash chain, and current.json parity.
    state = store.state()
    expected = {
        (
            item.source,
            item.identity,
            item.event_type,
            item.aggregate_type,
            item.aggregate_id,
            item.digest,
        )
        for item in records
    }
    actual: set[tuple[str, str, str, str, str, str]] = set()
    for event in store.events():
        migration = event.get("payload", {}).get("_migration")
        if not isinstance(migration, dict):
            continue
        actual.add(
            (
                str(migration.get("source")),
                str(migration.get("identity")),
                str(event.get("event_type")),
                str(event.get("aggregate_type")),
                str(event.get("aggregate_id")),
                str(migration.get("sha256")),
            )
        )
    missing_rows = sorted(expected - actual)
    def supplemental(row: tuple[str, str, str, str, str, str]) -> bool:
        source, identity = row[0], row[1]
        return (
            identity.startswith(
                (
                    "pages:",
                    "detail-page:",
                    "placeholder:",
                    "prior-knowledge-",
                    "scope-memory-",
                )
            )
            or source.endswith("/_live/acknowledged.json")
        )

    unexpected_rows = (
        []
        if legacy_sources_archived
        else sorted(row for row in actual - expected if not supplemental(row))
    )
    missing = [
        {
            "source": row[0],
            "identity": row[1],
            "event_type": row[2],
            "aggregate_type": row[3],
            "aggregate_id": row[4],
            "sha256": row[5],
        }
        for row in missing_rows
    ]
    unexpected = [
        {
            "source": row[0],
            "identity": row[1],
            "event_type": row[2],
            "aggregate_type": row[3],
            "aggregate_id": row[4],
            "sha256": row[5],
        }
        for row in unexpected_rows
    ]
    return {
        "ok": not missing and not unexpected,
        "expected": len(expected),
        "matched": len(expected) - len(missing),
        "missing": missing,
        "unexpected": unexpected,
        "legacy_sources_archived": legacy_sources_archived,
        "source_seq": state["source_seq"],
        "source_hash": state["source_hash"],
    }


def _seal_manifest(report: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(report)
    sealed.pop("manifest_sha256", None)
    sealed["manifest_sha256"] = _manifest_sha256(sealed)
    return sealed


def _write_migration_manifest(paths: ResearchPaths, report: dict[str, Any]) -> dict[str, Any]:
    sealed = _seal_manifest(report)
    write_json_atomic(paths.state / "migration.json", sealed)
    return sealed


def _load_migration_manifest(paths: ResearchPaths) -> dict[str, Any] | None:
    path = paths.state / "migration.json"
    if not path.exists():
        return None
    try:
        report = read_json(path)
    except json.JSONDecodeError as exc:
        raise MigrationError(f"malformed migration manifest {path}: {exc}") from exc
    if not isinstance(report, dict):
        raise MigrationError(f"migration manifest must contain an object: {path}")
    recorded = report.get("manifest_sha256")
    candidate = copy.deepcopy(report)
    candidate.pop("manifest_sha256", None)
    actual = _manifest_sha256(candidate)
    if recorded != actual:
        raise MigrationError(f"migration manifest tamper detected: {path}")
    return report


def _is_empty_migration_scaffold(paths: ResearchPaths) -> bool:
    if not paths.root.exists():
        return True
    allowed_roots = {"state", "audit", "experiments", "interface"}
    for entry in paths.root.rglob("*"):
        relative = entry.relative_to(paths.root)
        if relative.parts[0] not in allowed_roots:
            return False
        if entry.is_symlink():
            return False
        if entry.is_file():
            if relative.as_posix() == "state/.migration.lock" and entry.stat().st_size == 0:
                continue
            return False
        if not entry.is_dir():
            return False
    return True


def _verify_recorded_runs(
    paths: ResearchPaths,
    migrations: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    drift: list[dict[str, Any]] = []
    for item in migrations:
        destination_value = item.get("destination_path")
        if not isinstance(destination_value, str) or not destination_value:
            drift.append(
                {
                    "run_id": item.get("run_id"),
                    "code": "MIGRATION_DESTINATION_MISSING",
                }
            )
            continue
        destination = Path(destination_value)
        if not destination.is_absolute():
            destination = paths.workspace / destination
        destination = destination.resolve()
        try:
            destination.relative_to(paths.experiments.resolve())
        except ValueError:
            drift.append(
                {
                    "run_id": item.get("run_id"),
                    "code": "MIGRATION_DESTINATION_OUTSIDE_RESEARCH_ROOT",
                    "destination_path": str(destination),
                }
            )
            continue
        if not destination.is_dir():
            drift.append(
                {
                    "run_id": item.get("run_id"),
                    "code": "MIGRATED_RUN_MISSING",
                    "destination_path": str(destination),
                }
            )
            continue
        entries = _tree_manifest(destination)
        actual_tree = _manifest_sha256(entries)
        if actual_tree != item.get("destination_tree_sha256"):
            drift.append(
                {
                    "run_id": item.get("run_id"),
                    "code": "MIGRATED_RUN_DRIFT",
                    "expected": item.get("destination_tree_sha256"),
                    "actual": actual_tree,
                }
            )
        run_path = destination / "run.json"
        if not run_path.is_file():
            continue
        actual_run_hash = _sha256_file(run_path)
        if actual_run_hash != item.get("run_json_sha256"):
            drift.append(
                {
                    "run_id": item.get("run_id"),
                    "code": "RUN_JSON_DRIFT",
                    "expected": item.get("run_json_sha256"),
                    "actual": actual_run_hash,
                }
            )
    return drift


def _verify_state_notes(paths: ResearchPaths, state: dict[str, Any]) -> list[dict[str, Any]]:
    drift: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            uri = value.get("uri")
            digest = value.get("sha256")
            if (
                isinstance(uri, str)
                and uri.startswith("state/notes/")
                and isinstance(digest, str)
                and (uri, digest) not in seen
            ):
                seen.add((uri, digest))
                try:
                    expected = paths.note(digest)
                except ValueError as exc:
                    drift.append({"uri": uri, "code": "INVALID_NOTE_REF", "detail": str(exc)})
                else:
                    actual_path = paths.root / uri
                    if actual_path != expected or not actual_path.is_file():
                        drift.append({"uri": uri, "code": "MIGRATED_NOTE_MISSING"})
                    elif _sha256_file(actual_path) != digest:
                        drift.append({"uri": uri, "code": "MIGRATED_NOTE_DRIFT"})
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(state.get("aggregates", {}))
    return drift


def _frozen_interface_contract_gate() -> dict[str, Any]:
    """Run the repository's frozen human-interface contract once per process."""
    from lib.interface.parity import cached_check_contract

    try:
        result = cached_check_contract(include_visual=True)
        return {
            "ok": True,
            "status": "passed",
            "browser_version": result.browser_version,
            "font_fingerprint": result.font_fingerprint,
            "runtime_fingerprint": result.runtime_fingerprint,
            "dom_files": result.dom_files,
            "css_files": result.css_files,
            "visual_pages": result.visual_pages,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _legacy_interface_dom_gate(paths: ResearchPaths) -> dict[str, Any]:
    """Prove migration changed authority/path copy, not the legacy layout."""
    from lib.interface.parity import legacy_dom_parity_report

    try:
        return legacy_dom_parity_report(
            paths.workspace / LEGACY_INTERFACE,
            paths.interface,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _build_migration_interface(
    paths: ResearchPaths,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Prove the staged state can render before VERSION makes it authoritative."""
    from lib.interface import build_interface

    try:
        result = build_interface(paths, allow_unversioned_migration=True)
        required = {
            "index.html",
            "live.html",
            "learnings.html",
            "scope.html",
            "module.html",
        }
        for package_id, package in state["aggregates"]["package"].items():
            slug = (
                str(package.get("slug") or package_id)
                if isinstance(package, dict)
                else str(package_id)
            )
            required.update(
                f"packages/{slug}/{name}.html"
                for name in (
                    "index",
                    "plan",
                    "implementation",
                    "results",
                    "analysis",
                    "tracker",
                    "docs/index",
                )
            )
        present = {
            path.relative_to(paths.interface).as_posix()
            for path in result.files
        }
        missing = sorted(required - present)
        source_matches = (
            result.source_seq == int(state.get("source_seq") or 0)
            and result.source_hash == str(state.get("source_hash") or "")
        )
        projection_ok = not missing and source_matches
        frozen_contract = _frozen_interface_contract_gate()
        legacy_dom = _legacy_interface_dom_gate(paths)
        ok = projection_ok and frozen_contract["ok"] and legacy_dom["ok"]
        return {
            "ok": ok,
            "status": "passed" if ok else "failed",
            "files_written": len(result.files),
            "missing": missing,
            "source_seq": result.source_seq,
            "source_hash": result.source_hash,
            "source_matches": source_matches,
            "projection": {
                "ok": projection_ok,
                "status": "passed" if projection_ok else "failed",
                "missing": missing,
                "source_matches": source_matches,
            },
            "frozen_contract": frozen_contract,
            "legacy_dom_parity": legacy_dom,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "files_written": 0,
            "missing": [],
            "source_matches": False,
            "error": f"{type(exc).__name__}: {exc}",
            "projection": {
                "ok": False,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            },
            "frozen_contract": {
                "ok": False,
                "status": "not-run",
                "reason": "projection build failed",
            },
            "legacy_dom_parity": {
                "ok": False,
                "status": "not-run",
                "reason": "projection build failed",
            },
        }


def _check_finalized_workspace(
    paths: ResearchPaths,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    semantic: dict[str, Any] = {}
    records = discover(paths.workspace, paths, _semantic_out=semantic)
    legacy_markers = paths.legacy_markers()
    parity = _import_parity(
        paths,
        records,
        migration_mode=False,
        legacy_sources_archived=not legacy_markers,
    )
    note_drift = _verify_state_notes(paths, EventStore(paths).state())
    run_drift = _verify_recorded_runs(paths, manifest.get("run_migrations", []))
    source_drift: dict[str, Any] | None = None
    semantic_drift: dict[str, Any] | None = None
    authority = {
        "complete": True,
        "files": [],
        "by_classification": {},
        "families": {},
        "unresolved": [],
    }
    # After the documented legacy cleanup, no old marker remains.  The sealed
    # manifest is then the durable source-hash evidence; partial deletion or
    # mutation of a still-present legacy tree remains a hard drift failure.
    if legacy_markers:
        experiment_identities = _experiment_identity_index(records)
        runs = _discover_legacy_runs(
            paths.workspace / LEGACY_OUTPUTS,
            paths.workspace,
            experiment_identities=experiment_identities,
        )
        authority = _authority_inventory(paths.workspace, runs)
        current_source = _source_manifest(paths.workspace, runs)
        recorded_source = manifest.get("source_manifest")
        if current_source != recorded_source:
            source_drift = {
                "expected": recorded_source,
                "actual": current_source,
            }
        expected_semantic = manifest.get("semantic_fact_ledger", [])
        if semantic.get("blockers") or semantic.get("ledger", []) != expected_semantic:
            semantic_drift = {
                "expected": expected_semantic,
                "actual": semantic.get("ledger", []),
                "unresolved": semantic.get("blockers", []),
            }
    ok = (
        parity["ok"]
        and not note_drift
        and not run_drift
        and source_drift is None
        and semantic_drift is None
        and authority["complete"]
    )
    return {
        "ok": ok,
        "version": paths.load_version(),
        "parity": parity,
        "note_drift": note_drift,
        "run_drift": run_drift,
        "source_drift": source_drift,
        "semantic_drift": semantic_drift,
        "authority": authority,
        "manifest_sha256": manifest["manifest_sha256"],
    }


def migrate(paths: ResearchPaths) -> dict[str, Any]:
    """Explicitly import, verify, and atomically finalize a legacy workspace."""
    existing_version = paths.load_version()
    existing_manifest = _load_migration_manifest(paths)
    if existing_version is not None:
        if existing_manifest is None:
            raise MigrationError(
                f"{paths.version_file} exists without a sealed migration manifest"
            )
        verified = _check_finalized_workspace(paths, existing_manifest)
        if not verified["ok"]:
            raise MigrationError(
                "finalized migration drift detected: "
                + canonical_json(
                    {
                        "parity": verified["parity"],
                        "note_drift": verified["note_drift"],
                        "run_drift": verified["run_drift"],
                        "source_drift": verified["source_drift"],
                        "semantic_drift": verified["semantic_drift"],
                        "authority": verified["authority"]["unresolved"],
                    }
                )
            )
        if existing_manifest.get("status") != "complete":
            # Recover the narrow crash window after VERSION was durably
            # published but before the final manifest status was sealed.
            existing_manifest = _write_migration_manifest(
                paths,
                {
                    **copy.deepcopy(existing_manifest),
                    "status": "complete",
                    "ok": True,
                    "version_finalized": True,
                },
            )
        response = copy.deepcopy(existing_manifest)
        response.update(
            {
                "events_added": 0,
                "legacy_audit_added": 0,
                "already_current": True,
                "ok": True,
                "version_finalized": True,
            }
        )
        return response

    if existing_manifest is not None and existing_manifest.get("status") == "complete":
        raise MigrationError(
            f"completed migration manifest exists but {paths.version_file} is missing"
        )
    if (
        existing_manifest is None
        and paths.root.exists()
        and any(paths.root.iterdir())
        and not _is_empty_migration_scaffold(paths)
    ):
        raise MigrationError(
            f"unversioned research root has no sealed migration manifest: {paths.root}"
        )

    # Inventory is deliberately complete before the first .research write.
    semantic: dict[str, Any] = {}
    records = discover(paths.workspace, paths, _semantic_out=semantic)
    experiment_identities = _experiment_identity_index(records)
    runs = _discover_legacy_runs(
        paths.workspace / LEGACY_OUTPUTS,
        paths.workspace,
        experiment_identities=experiment_identities,
    )
    source_before = _source_manifest(paths.workspace, runs)
    inventory_report = inventory(
        paths.workspace,
        paths=paths,
        _precomputed=(records, runs),
        _semantic=semantic,
    )
    initial_blockers = [
        *copy.deepcopy(inventory_report["authority"]["unresolved"]),
        *copy.deepcopy(inventory_report["runs"]["unresolved"]),
        *copy.deepcopy(semantic.get("blockers", [])),
    ]

    paths.prepare_migration()
    with management_lock(paths.state / ".migration.lock", timeout=30.0):
        if paths.load_version() is not None:
            # Another explicit migrator won the race and published VERSION.
            return migrate(paths)
        locked_manifest = _load_migration_manifest(paths)
        if locked_manifest is None:
            _write_migration_manifest(
                paths,
                {
                    "schema_version": 1,
                    "target_version": CURRENT_VERSION,
                    "status": "inventory-complete",
                    "ok": False,
                    "version_finalized": False,
                    "inventory": inventory_report,
                    "legacy_records_discovered": len(records),
                    "events_added": 0,
                    "legacy_audit_added": 0,
                    "source_manifest": source_before,
                    "run_migrations": [],
                    "semantic_fact_ledger": copy.deepcopy(
                        semantic.get("ledger", [])
                    ),
                    "blockers": initial_blockers,
                    "gates": {
                        "inventory_complete": True,
                        "authority_classified": inventory_report["authority"]["complete"],
                        "import_parity": {"ok": False, "status": "pending"},
                        "source_stable": None,
                        "run_copy_parity": {"ok": False, "status": "pending"},
                        "semantic_fact_migration": copy.deepcopy(
                            semantic.get(
                                "gate",
                                {
                                    "ok": True,
                                    "status": "passed",
                                    "counts": {},
                                    "ledger": [],
                                    "unresolved": [],
                                },
                            )
                        ),
                        "interface_rebuild": {"ok": False, "status": "pending"},
                        "no_active_or_unresolved_runs": not bool(
                            initial_blockers
                        ),
                    },
                },
            )
        store = EventStore(paths, migration_mode=True)
        store.initialize()
        added = 0
        for item in records:
            added += int(_commit_legacy(store, item))
        prior_path = paths.workspace / LEGACY_OUTPUTS / "_scope" / "prior_knowledge.md"
        if prior_path.exists():
            note = store.write_note(
                prior_path.read_bytes(),
                title="Imported project prior knowledge",
            )
            projects = store.state()["aggregates"]["project"]
            project_id = sorted(projects)[0] if projects else "legacy-project"
            if project_id not in projects:
                added += int(
                    _commit_legacy(
                        store,
                        LegacyRecord(
                            "AggregateImported",
                            "project",
                            project_id,
                            {
                                "id": project_id,
                                "level": "project",
                                "parents": [],
                                "version": 1,
                                "status": "ACTIVE",
                                "spec": {},
                                "source": "legacy-migration",
                            },
                            _relative(prior_path, paths.workspace),
                            "prior-knowledge-project",
                        ),
                    )
                )
            added += int(
                _commit_legacy(
                    store,
                    LegacyRecord(
                        "AggregatePatched",
                        "project",
                        project_id,
                        {"prior_knowledge": note},
                        _relative(prior_path, paths.workspace),
                        "prior-knowledge-note",
                    ),
                )
            )
        memory_path = (
            paths.workspace / LEGACY_OUTPUTS / "_scope" / "memory.jsonl"
        )
        if memory_path.exists():
            # Parse before preserving the bytes so malformed legacy memory
            # fails migration instead of becoming an opaque, unusable blob.
            _jsonl(memory_path)
            note = store.write_note(
                memory_path.read_bytes(),
                mime="application/x-ndjson",
                title="Imported legacy Scope memory",
            )
            projects = store.state()["aggregates"]["project"]
            project_id = sorted(projects)[0] if projects else "legacy-project"
            if project_id not in projects:
                added += int(
                    _commit_legacy(
                        store,
                        LegacyRecord(
                            "AggregateImported",
                            "project",
                            project_id,
                            {
                                "id": project_id,
                                "level": "project",
                                "parents": [],
                                "version": 1,
                                "status": "ACTIVE",
                                "spec": {},
                                "source": "legacy-migration",
                            },
                            _relative(memory_path, paths.workspace),
                            "scope-memory-project",
                        ),
                    )
                )
            added += int(
                _commit_legacy(
                    store,
                    LegacyRecord(
                        "AggregatePatched",
                        "project",
                        project_id,
                        {"legacy_scope_memory": note},
                        _relative(memory_path, paths.workspace),
                        "scope-memory-note",
                    ),
                )
            )
        for item in _page_notes(paths.workspace, store) or []:
            if item.aggregate_id not in store.state()["aggregates"]["package"]:
                placeholder = LegacyRecord(
                    "AggregateImported",
                    "package",
                    item.aggregate_id,
                    {
                        "id": item.aggregate_id,
                        "slug": item.aggregate_id,
                        "lifecycle": "ACTIVE",
                        "phase": None,
                        "blocker": {
                            "code": "LEGACY_PACKAGE_STATE_UNKNOWN",
                            "summary": "Package pages existed without an inventory record.",
                        },
                    },
                    item.source,
                    f"placeholder:{item.aggregate_id}",
                )
                added += int(_commit_legacy(store, placeholder))
            added += int(_commit_legacy(store, item))
        for item in _brainstorm_page_notes(paths.workspace, store) or []:
            added += int(_commit_legacy(store, item))
        attention = _migrate_attention(paths.workspace, store)
        legacy_audit = _migrate_legacy_audit(paths.workspace, paths)

        blockers = [
            *copy.deepcopy(inventory_report["authority"]["unresolved"]),
            *_run_blockers(paths, runs),
            *copy.deepcopy(semantic.get("blockers", [])),
        ]
        blocked_run_ids = {
            str(item["run_id"])
            for item in blockers
            if item.get("run_id") is not None
        }
        run_migrations = [
            _copy_terminal_run(paths, run)
            for run in runs
            if run.terminal and run.run_id not in blocked_run_ids
        ]

        source_after = _source_manifest(paths.workspace, runs)
        source_stable = source_before == source_after
        if not source_stable:
            blockers.append(
                {
                    "code": "SOURCE_CHANGED_DURING_MIGRATION",
                    "before": source_before["sha256"],
                    "after": source_after["sha256"],
                }
            )
        parity = _import_parity(paths, records, migration_mode=True)
        if not parity["ok"]:
            blockers.append(
                {
                    "code": "IMPORT_PARITY_FAILED",
                    "missing": parity["missing"],
                    "unexpected": parity["unexpected"],
                }
            )
        run_drift = _verify_recorded_runs(paths, run_migrations)
        if run_drift:
            blockers.append(
                {
                    "code": "RUN_COPY_PARITY_FAILED",
                    "drift": run_drift,
                }
            )

        state = store.state()
        note_drift = _verify_state_notes(paths, state)
        if note_drift:
            blockers.append(
                {
                    "code": "NOTE_PARITY_FAILED",
                    "drift": note_drift,
                }
            )
        interface_rebuild = _build_migration_interface(paths, state)
        projection_gate = interface_rebuild.get("projection")
        if not isinstance(projection_gate, dict):
            projection_gate = {
                "ok": bool(interface_rebuild.get("ok")),
                "status": interface_rebuild.get("status", "failed"),
            }
        frozen_contract_gate = interface_rebuild.get("frozen_contract")
        legacy_dom_gate = interface_rebuild.get("legacy_dom_parity")
        if not projection_gate.get("ok"):
            blockers.append(
                {
                    "code": "INTERFACE_REBUILD_FAILED",
                    "detail": copy.deepcopy(projection_gate),
                }
            )
        if (
            isinstance(frozen_contract_gate, dict)
            and frozen_contract_gate.get("status") != "not-run"
            and not frozen_contract_gate.get("ok")
        ):
            blockers.append(
                {
                    "code": "INTERFACE_FROZEN_CONTRACT_FAILED",
                    "detail": copy.deepcopy(frozen_contract_gate),
                }
            )
        if (
            isinstance(legacy_dom_gate, dict)
            and legacy_dom_gate.get("status") != "not-run"
            and not legacy_dom_gate.get("ok")
        ):
            blockers.append(
                {
                    "code": "LEGACY_INTERFACE_DOM_PARITY_FAILED",
                    "detail": copy.deepcopy(legacy_dom_gate),
                }
            )
        report: dict[str, Any] = {
            "schema_version": 1,
            "target_version": CURRENT_VERSION,
            "status": "blocked" if blockers else "ready-to-finalize",
            "ok": not blockers,
            "version_finalized": False,
            "inventory": inventory_report,
            "legacy_records_discovered": len(records),
            "events_added": added + attention,
            "legacy_audit_added": legacy_audit,
            "source_seq": state["source_seq"],
            "source_hash": state["source_hash"],
            "source_manifest": source_after,
            "run_migrations": run_migrations,
            "semantic_fact_ledger": copy.deepcopy(
                semantic.get("ledger", [])
            ),
            "blockers": blockers,
            "gates": {
                "inventory_complete": True,
                "authority_classified": inventory_report["authority"]["complete"],
                "import_parity": parity,
                "source_stable": source_stable,
                "note_parity": {
                    "ok": not note_drift,
                    "drift": note_drift,
                },
                "run_copy_parity": {
                    "ok": not run_drift,
                    "migrated": len(run_migrations),
                    "drift": run_drift,
                },
                "semantic_fact_migration": copy.deepcopy(
                    semantic.get(
                        "gate",
                        {
                            "ok": True,
                            "status": "passed",
                            "counts": {},
                            "ledger": [],
                            "unresolved": [],
                        },
                    )
                ),
                "interface_rebuild": interface_rebuild,
                "frozen_interface_contract": frozen_contract_gate,
                "legacy_interface_dom_parity": legacy_dom_gate,
                "no_active_or_unresolved_runs": not any(
                    blocker.get("run_id") for blocker in blockers
                ),
            },
            "aggregate_counts": {
                key: len(value) for key, value in state["aggregates"].items()
            },
        }
        report = _write_migration_manifest(paths, report)
        if blockers:
            return report

        # VERSION is the commit marker and is written only after the sealed
        # ready-to-finalize manifest and every gate above are durable.
        paths.finalize_migration()
        report.update(
            {
                "status": "complete",
                "ok": True,
                "version_finalized": True,
            }
        )
        return _write_migration_manifest(paths, report)


def inventory(
    workspace: Path,
    *,
    paths: ResearchPaths | None = None,
    _precomputed: tuple[list[LegacyRecord], list[LegacyRun]] | None = None,
    _semantic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only inventory; this function never creates .research."""
    workspace = workspace.resolve()
    paths = paths or ResearchPaths.resolve(workspace=workspace)
    semantic = _semantic if _semantic is not None else {}
    if _precomputed is None:
        records = discover(workspace, paths, _semantic_out=semantic)
        experiment_identities = _experiment_identity_index(records)
        runs = _discover_legacy_runs(
            workspace / LEGACY_OUTPUTS,
            workspace,
            experiment_identities=experiment_identities,
        )
    else:
        records, runs = _precomputed
    counts: dict[str, int] = {}
    for item in records:
        counts[item.aggregate_type] = counts.get(item.aggregate_type, 0) + 1
    authority = _authority_inventory(workspace, runs)
    return {
        "workspace": str(workspace),
        "legacy_records": len(records),
        "by_aggregate": counts,
        "sources": sorted({item.source for item in records}),
        "source_manifest": _source_manifest(workspace, runs),
        "authority": authority,
        "semantic_facts": copy.deepcopy(
            semantic.get(
                "gate",
                {
                    "ok": True,
                    "status": "passed",
                    "counts": {},
                    "ledger": [],
                    "unresolved": [],
                },
            )
        ),
        "runs": {
            "total": len(runs),
            "terminal": sum(run.terminal for run in runs),
            "active": sum(run.status in ACTIVE_RUN_STATUSES for run in runs),
            "unresolved": _run_blockers(paths, runs),
        },
    }


def check(paths: ResearchPaths) -> dict[str, Any]:
    version = paths.load_version()
    manifest = _load_migration_manifest(paths)
    if manifest is None:
        return {
            "ok": False,
            "version": version,
            "error": "migration manifest is missing",
        }
    if version is not None:
        return _check_finalized_workspace(paths, manifest)

    semantic: dict[str, Any] = {}
    records = discover(paths.workspace, paths, _semantic_out=semantic)
    parity = _import_parity(paths, records, migration_mode=True)
    note_drift = _verify_state_notes(
        paths,
        EventStore(paths, migration_mode=True).state(),
    )
    experiment_identities = _experiment_identity_index(records)
    runs = _discover_legacy_runs(
        paths.workspace / LEGACY_OUTPUTS,
        paths.workspace,
        experiment_identities=experiment_identities,
    )
    authority = _authority_inventory(paths.workspace, runs)
    source = _source_manifest(paths.workspace, runs)
    source_drift = (
        None
        if source == manifest.get("source_manifest")
        else {
            "expected": manifest.get("source_manifest"),
            "actual": source,
        }
    )
    run_drift = _verify_recorded_runs(paths, manifest.get("run_migrations", []))
    return {
        "ok": False,
        "version": None,
        "status": manifest.get("status"),
        "parity": parity,
        "note_drift": note_drift,
        "blockers": manifest.get("blockers", []),
        "run_drift": run_drift,
        "source_drift": source_drift,
        "semantic_fact_migration": copy.deepcopy(
            semantic.get("gate", {})
        ),
        "authority": authority,
        "manifest_sha256": manifest["manifest_sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="research-migrate")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory")
    sub.add_parser("migrate")
    sub.add_parser("check")
    args = parser.parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    if args.command == "inventory":
        result = inventory(paths.workspace, paths=paths)
    elif args.command == "migrate":
        result = migrate(paths)
    else:
        result = check(paths)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
