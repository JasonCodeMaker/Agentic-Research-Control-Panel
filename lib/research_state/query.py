"""Bounded, hash-stamped reads over management state and audit."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from .io import canonical_json
from .paths import ResearchPaths
from .store import CommandRejected, EventStore


DEFAULT_COMPACT_CONTEXT_BUDGET = 4_000


def _verified_note_text(paths: ResearchPaths, ref: Any) -> str:
    if not isinstance(ref, Mapping):
        raise CommandRejected(
            "draft-package-document-required",
            "Draft Package context requires a proposal document NoteRef",
        )
    digest = str(ref.get("sha256") or "")
    uri = str(ref.get("uri") or "")
    if uri != f"state/notes/{digest}.md":
        raise CommandRejected(
            "draft-package-document-ref-invalid",
            "Draft Package proposal NoteRef is not canonical",
        )
    raw = paths.note(digest).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise CommandRejected(
            "draft-package-document-hash-mismatch",
            "Draft Package proposal document no longer matches governed state",
        )
    return raw.decode("utf-8")


def _experiment_identifier_tokens(value: Any) -> set[str]:
    """Collect canonical and compatibility identifiers from one reference."""
    if isinstance(value, Mapping):
        tokens: set[str] = set()
        for field in (
            "aggregate_id",
            "scope_experiment_id",
            "id",
            "local_id",
            "localId",
            "aliases",
        ):
            tokens.update(_experiment_identifier_tokens(value.get(field)))
        return tokens
    if isinstance(value, (list, tuple, set, frozenset)):
        tokens: set[str] = set()
        for item in value:
            tokens.update(_experiment_identifier_tokens(item))
        return tokens
    return {str(value)} if value not in (None, "") else set()


def _context_action(package: Mapping[str, Any]) -> str:
    if package.get("lifecycle") == "DRAFT":
        return "REFINE_DRAFT"
    return {
        "CONTEXT_LOADED": "IMPLEMENT_PACKAGE",
        "IMPLEMENTING": "IMPLEMENT_PACKAGE",
        "READY_TO_LAUNCH": "LAUNCH_EXPERIMENT",
        "RUNNING": "MONITOR_RUN",
        "RESULT_REVIEW": "REVIEW_RESULT",
    }.get(str(package.get("phase") or ""), "QUERY_PACKAGE")


def _rule_applies(rule: Mapping[str, Any], package_id: str) -> bool:
    if rule.get("status") not in {"ACTIVE", "PROMOTED", "RULE_ACTIVE"}:
        return False
    level = rule.get("level")
    if level in {"universal", "project"}:
        return True
    if level != "package":
        return False
    if (rule.get("package_id") or rule.get("pkg")) == package_id:
        return True
    scope = rule.get("scope") if isinstance(rule.get("scope"), Mapping) else {}
    return package_id in set(scope.get("packages") or [])


def _evidence_refs(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        refs = (
            record.get("evidence_refs")
            or record.get("evidenceRefs")
            or record.get("evidence")
            or []
        )
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            identity = canonical_json(ref)
            if identity in seen:
                continue
            seen.add(identity)
            selected.append(copy.deepcopy(ref))
    return selected


def resolve_bound_experiment(
    experiments: Mapping[str, Any],
    package_id: str,
    requested: Any,
) -> tuple[str, dict[str, Any]]:
    """Resolve exactly one Package-bound Experiment.

    The accepted Scope id is canonical. Package-local ids, explicit aliases,
    and the retired ``<package>::<local>`` shape are read-only lookup handles.
    Ambiguity fails closed instead of depending on iteration order.
    """
    requested_tokens = _experiment_identifier_tokens(requested)
    if not requested_tokens:
        raise ValueError(
            f"Experiment identifier is required for package {package_id}"
        )
    matches: list[tuple[str, dict[str, Any]]] = []
    for aggregate_id, raw in experiments.items():
        if (
            not isinstance(raw, dict)
            or str(raw.get("package_id") or "") != str(package_id)
        ):
            continue
        record_tokens = _experiment_identifier_tokens(
            {**raw, "aggregate_id": str(aggregate_id)}
        )
        local_id = raw.get("local_id") or raw.get("localId")
        if local_id not in (None, ""):
            record_tokens.add(f"{package_id}::{local_id}")
        if requested_tokens.intersection(record_tokens):
            matches.append((str(aggregate_id), raw))
    if len(matches) != 1:
        matched_ids = [aggregate_id for aggregate_id, _ in matches]
        raise ValueError(
            f"expected one bound Experiment in package {package_id} for "
            f"{sorted(requested_tokens)!r}; found {len(matches)} "
            f"{matched_ids!r}"
        )
    return matches[0]


class StateQuery:
    def __init__(self, paths: ResearchPaths):
        self.paths = paths
        self.store = EventStore(paths)

    def _state(self) -> dict[str, Any]:
        return self.store.state()

    @staticmethod
    def _stamp(state: dict[str, Any], value: Any) -> dict[str, Any]:
        return {
            "source_seq": state["source_seq"],
            "source_hash": state["source_hash"],
            "data": copy.deepcopy(value),
        }

    def show(
        self,
        aggregate_type: str,
        aggregate_id: str | None = None,
    ) -> dict[str, Any]:
        state = self._state()
        if aggregate_type == "open_run":
            value: Any = state["open_runs"]
        else:
            if aggregate_type not in state["aggregates"]:
                raise KeyError(f"unknown aggregate type: {aggregate_type}")
            bucket = state["aggregates"][aggregate_type]
            if aggregate_id is None:
                value = bucket
            else:
                if aggregate_id not in bucket:
                    raise KeyError(f"unknown {aggregate_type}: {aggregate_id}")
                value = bucket[aggregate_id]
        return self._stamp(state, value)

    def history(self, aggregate_type: str, aggregate_id: str) -> dict[str, Any]:
        state, snapshot_events, _ = self.store.snapshot()
        events = [
            event
            for event in snapshot_events
            if (
                event["aggregate_type"] == aggregate_type
                and event["aggregate_id"] == aggregate_id
            )
            or (
                event["event_type"] == "TransactionCommitted"
                and any(
                    isinstance(participant, dict)
                    and participant.get("aggregate_type") == aggregate_type
                    and participant.get("aggregate_id") == aggregate_id
                    for participant in event.get("payload", {}).get(
                        "participants", []
                    )
                )
            )
            or (
                aggregate_type == "experiment"
                and event["event_type"]
                in {
                    "PackageMaterialized",
                    "PackageActivated",
                    "PackageExperimentBound",
                    "PackageReopenedAsDraft",
                }
                and any(
                    isinstance(binding, dict)
                    and binding.get("aggregate_id") == aggregate_id
                    for binding in event.get("payload", {}).get(
                        "experiment_unbindings"
                        if event["event_type"] == "PackageReopenedAsDraft"
                        else "experiment_restorations"
                        if event["event_type"] == "PackageActivated"
                        and isinstance(
                            event.get("payload", {}).get("reopen_reactivation"),
                            dict,
                        )
                        else "experiment_bindings",
                        [],
                    )
                )
            )
            or (
                aggregate_type == "brainstorm"
                and event["event_type"]
                in {
                    "PackageDraftCreated",
                    "PackageMaterialized",
                    "PackageMutationApplied",
                }
                and any(
                    isinstance(consumption, dict)
                    and consumption.get("aggregate_id") == aggregate_id
                    for consumption in event.get("payload", {}).get(
                        "brainstorm_consumptions", []
                    )
                )
            )
            or (
                aggregate_type in {"proposal", "direction"}
                and event["event_type"] == "PackageActivated"
                and isinstance(
                    event.get("payload", {}).get("scope_finalization"),
                    dict,
                )
                and event["payload"]["scope_finalization"]
                .get(aggregate_type, {})
                .get("aggregate_id")
                == aggregate_id
            )
        ]
        return self._stamp(state, events)

    def audit(self, command_id: str) -> dict[str, Any]:
        state, _, snapshot_audit = self.store.snapshot(include_audit=True)
        rows = [
            row
            for row in snapshot_audit
            if row.get("command_id") == command_id
        ]
        return self._stamp(state, rows)

    def context(self, package_id: str, *, phase: str | None = None) -> dict[str, Any]:
        """Return the bounded, ephemeral Context Pack for one package.

        Unlike ``show package/<id>``, this deliberately excludes full Run
        history and resolved Decisions.  It includes only the package control
        boundary, ratified Experiment specs, pending governance, applicable
        Rules/Learnings, and cross-project knowledge selected by the Context
        Pack budget.
        """
        state = self._state()
        packages = state["aggregates"]["package"]
        if package_id not in packages:
            raise KeyError(f"unknown package: {package_id}")
        package = packages[package_id]
        if phase is not None and package.get("phase") != phase:
            raise ValueError(
                f"package phase is {package.get('phase')!r}, requested {phase!r}"
            )
        if package.get("lifecycle") == "DRAFT":
            project_boundary = []
            for project_id, raw in state["aggregates"]["project"].items():
                if not isinstance(raw, dict) or raw.get("status") != "ACTIVE":
                    continue
                spec = raw.get("spec") if isinstance(raw.get("spec"), dict) else {}
                project_boundary.append(
                    {
                        "id": str(project_id),
                        "goal": spec.get("goal"),
                        "out_of_scope": copy.deepcopy(spec.get("out_of_scope", [])),
                    }
                )
            pending_scope = []
            for proposal_id, raw in state["aggregates"]["proposal"].items():
                if not isinstance(raw, dict) or raw.get("disposition") != "PENDING":
                    continue
                source = raw.get("source_package")
                if isinstance(source, dict) and source.get("id") == package_id:
                    pending_scope.append(
                        {
                            "id": str(proposal_id),
                            "level": raw.get("level"),
                            "node_id": raw.get("node_id"),
                            "proposal_hash": raw.get("proposal_hash"),
                            "source_package": copy.deepcopy(source),
                        }
                    )
            note = package.get("document_note")
            return self._stamp(
                state,
                {
                    "package": copy.deepcopy(package),
                    "proposal_document": {
                        "path": package.get("documentPath"),
                        "note": copy.deepcopy(note),
                        "html_fragment": _verified_note_text(self.paths, note),
                    },
                    "project_boundary": sorted(
                        project_boundary,
                        key=lambda row: row["id"],
                    ),
                    "pending_scope": sorted(
                        pending_scope,
                        key=lambda row: row["id"],
                    ),
                    "execution_authorized": False,
                },
            )
        direction_id = package.get("direction_id") or package.get("sourceDirection")
        direction = state["aggregates"]["direction"].get(direction_id)
        direction_version = (
            direction.get("version") if isinstance(direction, dict) else None
        )
        if (
            not isinstance(direction, dict)
            or direction.get("status") != "ACTIVE"
            or not isinstance(direction_version, int)
        ):
            raise CommandRejected(
                "scope-context-direction-invalid",
                "package context requires a current ACTIVE Direction",
            )
        stale_experiments = []
        for experiment_id, experiment in state["aggregates"]["experiment"].items():
            if (
                not isinstance(experiment, dict)
                or experiment.get("package_id") != package_id
            ):
                continue
            confirmed_version = experiment.get("confirmed_direction_version")
            if (
                experiment.get("scope_confirmation") != "CONFIRMED"
                or experiment.get("scope_status") != "ACTIVE"
                or confirmed_version != direction_version
            ):
                stale_experiments.append(str(experiment_id))
        if stale_experiments:
            raise CommandRejected(
                "scope-context-stale",
                "package context is blocked until these Experiment specs are "
                "reconfirmed against the current Direction: "
                + ", ".join(sorted(stale_experiments)),
            )
        # Lazy import avoids making research_state's package import depend on
        # the optional Markdown renderer.
        from lib.context_pack.build import query_json

        return self._stamp(
            state,
            query_json(
                self.paths,
                package_id,
                state_snapshot=state,
            ),
        )

    def compact_context(
        self,
        package_id: str,
        *,
        phase: str | None = None,
        experiment_id: str | None = None,
        budget_chars: int = DEFAULT_COMPACT_CONTEXT_BUDGET,
    ) -> dict[str, Any]:
        """Return one hard-bounded agent action packet.

        Full proposal text, history, resolved Decisions, and cross-project
        overlays stay behind ``context``. Every omitted category is reported;
        if the mandatory intent and constraints do not fit, the query fails
        instead of silently dropping authority.
        """
        if budget_chars < 512:
            raise ValueError("compact context budget must be at least 512 characters")
        state = self._state()
        package = state["aggregates"]["package"].get(package_id)
        if not isinstance(package, dict):
            raise KeyError(f"unknown package: {package_id}")
        if phase is not None and package.get("phase") != phase:
            raise ValueError(
                f"package phase is {package.get('phase')!r}, requested {phase!r}"
            )

        if package.get("lifecycle") == "DRAFT":
            note = package.get("document_note")
            _verified_note_text(self.paths, note)
            projects = []
            for project_id, raw in state["aggregates"]["project"].items():
                if not isinstance(raw, dict) or raw.get("status") != "ACTIVE":
                    continue
                spec = raw.get("spec") if isinstance(raw.get("spec"), dict) else {}
                projects.append(
                    {
                        "id": str(project_id),
                        "goal": spec.get("goal"),
                        "out_of_scope": copy.deepcopy(spec.get("out_of_scope", [])),
                    }
                )
            data: dict[str, Any] = {
                "view": "compact",
                "action": {"kind": "REFINE_DRAFT"},
                "selection": {
                    "package": {
                        "id": package_id,
                        "lifecycle": "DRAFT",
                        "phase": package.get("phase"),
                        "blocker": package.get("blocker"),
                    },
                    "experiments": [],
                    "pending_decision_ids": [],
                    "evidence_refs": [],
                },
                "draft": {
                    "id": package_id,
                    "title": package.get("title") or package.get("name"),
                    "abstract": package.get("abstract"),
                    "draft_revision": package.get("draftRevision"),
                    "document_path": package.get("documentPath"),
                    "document_note": copy.deepcopy(note),
                    "execution_authorized": False,
                },
                "project_boundary": sorted(projects, key=lambda row: row["id"]),
                "constraints": ["Draft Package has no execution authority"],
                "omitted": {
                    "proposal_document_html": 1,
                    "full_package_fields": max(len(package) - 8, 0),
                    "history": True,
                },
            }
            return self._bounded_context(state, data, budget_chars)

        direction_id = package.get("direction_id") or package.get("sourceDirection")
        direction = state["aggregates"]["direction"].get(direction_id)
        direction_version = (
            direction.get("version") if isinstance(direction, dict) else None
        )
        if (
            not isinstance(direction, dict)
            or direction.get("status") != "ACTIVE"
            or not isinstance(direction_version, int)
        ):
            raise CommandRejected(
                "scope-context-direction-invalid",
                "package context requires a current ACTIVE Direction",
            )

        bound = [
            (str(aggregate_id), raw)
            for aggregate_id, raw in state["aggregates"]["experiment"].items()
            if isinstance(raw, dict) and raw.get("package_id") == package_id
        ]
        stale = [
            aggregate_id
            for aggregate_id, experiment in bound
            if experiment.get("scope_confirmation") != "CONFIRMED"
            or experiment.get("scope_status") != "ACTIVE"
            or experiment.get("confirmed_direction_version") != direction_version
        ]
        if stale:
            raise CommandRejected(
                "scope-context-stale",
                "package context is blocked until these Experiment specs are "
                "reconfirmed against the current Direction: "
                + ", ".join(sorted(stale)),
            )
        if experiment_id is not None:
            selected_id, selected_record = resolve_bound_experiment(
                state["aggregates"]["experiment"],
                package_id,
                experiment_id,
            )
            selected = [(selected_id, selected_record)]
        else:
            selected = sorted(bound, key=lambda row: row[0])

        project = None
        for parent_id in direction.get("parents") or []:
            candidate = state["aggregates"]["project"].get(parent_id)
            if isinstance(candidate, dict):
                project = candidate
                break
        if project is None:
            project = next(
                (
                    raw
                    for raw in state["aggregates"]["project"].values()
                    if isinstance(raw, dict) and raw.get("status") == "ACTIVE"
                ),
                None,
            )

        rules = [
            raw
            for raw in state["aggregates"]["rule"].values()
            if isinstance(raw, dict) and _rule_applies(raw, package_id)
        ]
        constraints = [
            str(
                rule.get("text")
                or rule.get("content")
                or rule.get("description")
                or ""
            )
            for rule in rules
        ]
        constraints = [value for value in constraints if value]
        pending_values = {
            "PENDING",
            "AWAITING_ACK",
            "AWAITING_APPROVAL",
            "AWAITING_RATIFICATION",
            "ASK_USER",
        }
        pending = [
            raw
            for raw in state["aggregates"]["decision"].values()
            if isinstance(raw, dict)
            and (
                raw.get("package_id") == package_id
                or raw.get("subject_id") == package_id
                or raw.get("experiment_id") in {identity for identity, _ in bound}
            )
            and (
                raw.get("pending") is True
                or raw.get("requires_action") is True
                or raw.get("status") in pending_values
                or raw.get("outcome") in pending_values
                or raw.get("route") in pending_values
            )
        ]
        evidence = _evidence_refs(
            [package, *(record for _, record in selected), *rules, *pending]
        )
        shown_evidence = evidence[:4]
        project_spec = (
            copy.deepcopy(project.get("spec"))
            if isinstance(project, dict) and isinstance(project.get("spec"), dict)
            else None
        )
        data = {
            "view": "compact",
            "action": {
                "kind": _context_action(package),
                "experiment_id": selected[0][0] if len(selected) == 1 else None,
            },
            "selection": {
                "package": {
                    key: copy.deepcopy(package.get(key))
                    for key in ("id", "lifecycle", "phase", "blocker")
                },
                "experiments": [
                    {
                        "id": identity,
                        "status": record.get("status"),
                        "control_mode": (
                            record.get("spec", {}).get("control_mode")
                            if isinstance(record.get("spec"), dict)
                            else None
                        ),
                    }
                    for identity, record in selected
                ],
                "pending_decision_ids": sorted(
                    str(row.get("id")) for row in pending if row.get("id")
                ),
                "evidence_refs": shown_evidence,
            },
            "intent": {
                "project": (
                    {"id": project.get("id"), "spec": project_spec}
                    if isinstance(project, dict)
                    else None
                ),
                "direction": {
                    "id": direction.get("id") or direction_id,
                    "version": direction_version,
                    "spec": copy.deepcopy(direction.get("spec")),
                },
                "experiments": [
                    {
                        "id": identity,
                        "status": record.get("status"),
                        "spec": copy.deepcopy(record.get("spec")),
                    }
                    for identity, record in selected
                ],
            },
            "execution_lease": copy.deepcopy(package.get("executionLease")),
            "constraints": constraints,
            "omitted": {
                "unselected_experiments": len(bound) - len(selected),
                "evidence_refs": len(evidence) - len(shown_evidence),
                "learnings": len(state["aggregates"]["learning"]),
                "resolved_decisions": len(state["aggregates"]["decision"]) - len(pending),
                "history": True,
            },
        }
        return self._bounded_context(state, data, budget_chars)

    @classmethod
    def _bounded_context(
        cls,
        state: dict[str, Any],
        data: dict[str, Any],
        budget_chars: int,
    ) -> dict[str, Any]:
        packet = cls._stamp(state, data)
        serialized_chars = len(canonical_json(packet))
        packet["data"]["budget"] = {
            "limit_chars": budget_chars,
            "serialized_chars": serialized_chars,
            "truncated": any(
                bool(value)
                for value in packet["data"].get("omitted", {}).values()
            ),
        }
        serialized_chars = len(canonical_json(packet))
        packet["data"]["budget"]["serialized_chars"] = serialized_chars
        if len(canonical_json(packet)) > budget_chars:
            raise CommandRejected(
                "compact-context-budget-exceeded",
                "mandatory intent and constraints exceed the compact context "
                f"budget of {budget_chars} characters; select one Experiment "
                "or request --full for explicit audit context",
            )
        return packet

    def analysis(self, package_id: str | None = None) -> dict[str, Any]:
        """Return only fields required by the state-backed Analysis editor."""
        state = self._state()
        packages: list[dict[str, Any]] = []
        selected_ids: set[str] = set()
        for candidate_id, raw in state["aggregates"]["package"].items():
            if not isinstance(raw, dict):
                continue
            if package_id is not None and str(candidate_id) != package_id:
                continue
            if package_id is None and "analysis" not in (raw.get("pages") or []):
                continue
            selected_ids.add(str(candidate_id))
            packages.append(
                {
                    "id": str(candidate_id),
                    "pages": copy.deepcopy(raw.get("pages")),
                    "analysisInsights": copy.deepcopy(
                        raw.get("analysisInsights", [])
                    ),
                }
            )
        rules = []
        for aggregate_id, raw in state["aggregates"]["rule"].items():
            if not isinstance(raw, dict):
                continue
            owner = str(raw.get("package_id") or raw.get("pkg") or "")
            if owner not in selected_ids:
                continue
            rules.append(
                {
                    "id": str(raw.get("id") or aggregate_id),
                    "package_id": owner,
                    "kind": raw.get("kind"),
                    "status": raw.get("status"),
                    "text": raw.get("text"),
                    "rationale": raw.get("rationale"),
                }
            )
        return self._stamp(
            state,
            {
                "packages": sorted(packages, key=lambda row: row["id"]),
                "rules": sorted(rules, key=lambda row: row["id"]),
            },
        )

    def brainstorms(
        self,
        *,
        idea_id: str | None = None,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        """Return standalone Brainstorms; Draft Packages use the package view."""
        state = self._state()
        items = []
        versions: dict[str, int] = {}
        for aggregate_id, raw in state["aggregates"]["brainstorm"].items():
            candidate_id = str(aggregate_id)
            if idea_id is not None and candidate_id != idea_id:
                continue
            if not isinstance(raw, dict):
                continue
            row = copy.deepcopy(raw)
            row.setdefault("id", candidate_id)
            row["_aggregate_type"] = "brainstorm"
            if not include_archived and row.get("status", "ACTIVE") != "ACTIVE":
                continue
            items.append(row)
            versions[candidate_id] = int(
                state["aggregate_versions"].get(
                    f"brainstorm/{candidate_id}",
                    0,
                )
            )
        return self._stamp(
            state,
            {
                "items": sorted(items, key=lambda row: str(row["id"])),
                "versions": versions,
            },
        )

    def project_boundary(self) -> dict[str, Any]:
        """Return the active Project goal boundary, not the Project bucket."""
        state = self._state()
        projects = []
        for project_id, raw in state["aggregates"]["project"].items():
            if not isinstance(raw, dict) or raw.get("status") != "ACTIVE":
                continue
            spec = raw.get("spec") if isinstance(raw.get("spec"), dict) else {}
            projects.append(
                {
                    "id": str(project_id),
                    "goal": spec.get("goal"),
                    "out_of_scope": copy.deepcopy(spec.get("out_of_scope", [])),
                }
            )
        return self._stamp(
            state,
            sorted(projects, key=lambda row: row["id"]),
        )

    def pending_directions(
        self,
        direction_id: str | None = None,
    ) -> dict[str, Any]:
        """Return pending Direction proposals, optionally for one target."""
        state = self._state()
        rows = []
        for proposal_id, raw in state["aggregates"]["proposal"].items():
            if not isinstance(raw, dict) or raw.get("disposition") != "PENDING":
                continue
            proposed = raw.get("proposed_node")
            level = (
                proposed.get("level")
                if isinstance(proposed, dict)
                else raw.get("level")
            )
            target = (
                proposed.get("id")
                if isinstance(proposed, dict)
                else raw.get("node_id")
            )
            if level != "direction":
                continue
            if direction_id is not None and target != direction_id:
                continue
            row = {
                key: copy.deepcopy(raw.get(key))
                for key in (
                    "id",
                    "level",
                    "node_id",
                    "disposition",
                    "proposed_node",
                )
                if raw.get(key) is not None
            }
            row.setdefault("id", str(proposal_id))
            rows.append(row)
        return self._stamp(state, rows)

    def campaign(
        self,
        direction_id: str,
        *,
        package_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the minimal Direction-campaign routing/witness slice."""
        state = self._state()
        direction = state["aggregates"]["direction"].get(direction_id)
        direction_value = (
            {
                "id": direction_id,
                "status": direction.get("status"),
                "spec": copy.deepcopy(direction.get("spec", {})),
            }
            if isinstance(direction, dict)
            else None
        )
        pending = []
        for proposal_id, raw in state["aggregates"]["proposal"].items():
            if not isinstance(raw, dict) or raw.get("disposition") != "PENDING":
                continue
            proposed = raw.get("proposed_node")
            level = (
                proposed.get("level")
                if isinstance(proposed, dict)
                else raw.get("level")
            )
            target = (
                proposed.get("id")
                if isinstance(proposed, dict)
                else raw.get("node_id")
            )
            if level == "direction" and target == direction_id:
                row = {
                    key: copy.deepcopy(raw.get(key))
                    for key in (
                        "id",
                        "level",
                        "node_id",
                        "disposition",
                        "proposed_node",
                    )
                    if raw.get(key) is not None
                }
                row.setdefault("id", str(proposal_id))
                pending.append(row)
        packages = []
        selected_package_ids: set[str] = set()
        for candidate_id, raw in state["aggregates"]["package"].items():
            if not isinstance(raw, dict):
                continue
            if (
                raw.get("direction_id") != direction_id
                and raw.get("sourceDirection") != direction_id
            ):
                continue
            candidate_id = str(candidate_id)
            if package_id is not None and candidate_id != package_id:
                continue
            selected_package_ids.add(candidate_id)
            packages.append(
                {
                    "id": candidate_id,
                    "lifecycle": raw.get("lifecycle"),
                }
            )
        experiments: dict[str, dict[str, Any]] = {}
        for aggregate_id, raw in state["aggregates"]["experiment"].items():
            if (
                not isinstance(raw, dict)
                or str(raw.get("package_id") or "") not in selected_package_ids
            ):
                continue
            experiments[str(aggregate_id)] = {
                key: copy.deepcopy(raw.get(key))
                for key in (
                    "id",
                    "local_id",
                    "localId",
                    "aliases",
                    "package_id",
                    "status",
                )
                if raw.get(key) is not None
            }
        aggregate_id = direction_id
        campaign = state["aggregates"]["campaign"].get(aggregate_id)
        run = (
            state["aggregates"]["run"].get(run_id)
            if run_id is not None
            else None
        )
        run_value = (
            {
                key: copy.deepcopy(run.get(key))
                for key in (
                    "id",
                    "package_id",
                    "experiment_id",
                    "experiment_local_id",
                    "status",
                )
                if run.get(key) is not None
            }
            if isinstance(run, dict)
            else None
        )
        return self._stamp(
            state,
            {
                "direction": direction_value,
                "pending_directions": pending,
                "packages": sorted(packages, key=lambda row: row["id"]),
                "experiments": experiments,
                "campaign": (
                    {
                        key: copy.deepcopy(campaign.get(key))
                        for key in (
                            "direction_id",
                            "cycles",
                            "packs",
                            "status",
                            "route",
                        )
                        if campaign.get(key) is not None
                    }
                    if isinstance(campaign, dict)
                    else None
                ),
                "campaign_version": int(
                    state["aggregate_versions"].get(
                        f"campaign/{aggregate_id}",
                        0,
                    )
                ),
                "run": run_value,
            },
        )

    def materialization(
        self,
        direction_id: str,
        package_id: str,
    ) -> dict[str, Any]:
        """Return only records needed to decide Direction materialization."""
        state, events, _ = self.store.snapshot()
        direction = state["aggregates"]["direction"].get(direction_id)
        source_brainstorm_ids: list[str] = []
        source_package: dict[str, Any] | None = None
        source_proposal_id: str | None = None
        has_typed_source_provenance = False
        if isinstance(direction, dict):
            transition = direction.get("_scope_transition")
            trigger = (
                transition.get("trigger")
                if isinstance(transition, dict)
                else None
            )
            if isinstance(trigger, str) and trigger.startswith("triage:"):
                source_proposal_id = trigger.removeprefix("triage:")
                proposal = state["aggregates"]["proposal"].get(source_proposal_id)
                accepted = (
                    proposal.get("accepted_proposal")
                    if isinstance(proposal, dict)
                    and proposal.get("disposition") == "ACCEPTED"
                    else None
                )
                proposed_node = (
                    accepted.get("proposed_node")
                    if isinstance(accepted, dict)
                    else None
                )
                raw_ids = (
                    accepted.get("source_brainstorms")
                    if isinstance(accepted, dict)
                    and isinstance(proposed_node, dict)
                    and proposed_node.get("id") == direction_id
                    and proposed_node.get("version") == direction.get("version")
                    else None
                )
                if isinstance(accepted, dict) and "source_brainstorms" in accepted:
                    has_typed_source_provenance = True
                    if not isinstance(raw_ids, list) or not all(
                        isinstance(item, str) and item for item in raw_ids
                    ):
                        raise CommandRejected(
                            "direction-source-brainstorms-invalid",
                            "accepted Direction source_brainstorms must be a list "
                            "of non-empty ids",
                        )
                    source_brainstorm_ids = list(dict.fromkeys(raw_ids))
                raw_source_package = (
                    accepted.get("source_package")
                    if isinstance(accepted, dict)
                    and isinstance(proposed_node, dict)
                    and proposed_node.get("id") == direction_id
                    and proposed_node.get("version") == direction.get("version")
                    else None
                )
                if raw_source_package is not None:
                    if (
                        not isinstance(raw_source_package, dict)
                        or set(raw_source_package)
                        != {"id", "draft_revision", "document_sha256"}
                    ):
                        raise CommandRejected(
                            "direction-source-package-invalid",
                            "accepted Direction source_package is malformed",
                        )
                    source_package = copy.deepcopy(raw_source_package)
            if not has_typed_source_provenance:
                source = direction.get("source")
                if isinstance(source, str) and source.startswith("brainstorms:"):
                    source_brainstorm_ids = [
                        item.strip()
                        for item in source.removeprefix("brainstorms:").split(",")
                        if item.strip()
                    ]
        source_brainstorms = []
        missing_source_brainstorms = []
        for idea_id in source_brainstorm_ids:
            raw = state["aggregates"]["brainstorm"].get(idea_id)
            if not isinstance(raw, dict) or raw.get("status") != "ACTIVE":
                missing_source_brainstorms.append(idea_id)
                continue
            source_brainstorms.append(
                {
                    "aggregate_id": idea_id,
                    "aggregate_version": int(
                        state["aggregate_versions"].get(
                            f"brainstorm/{idea_id}",
                            0,
                        )
                    ),
                    "record": copy.deepcopy(raw),
                }
            )
        experiments: dict[str, dict[str, Any]] = {}
        for aggregate_id, raw in state["aggregates"]["experiment"].items():
            if not isinstance(raw, dict) or raw.get("direction_id") != direction_id:
                continue
            if raw.get("package_id") not in (None, ""):
                continue
            if raw.get("scope_status") != "ACTIVE":
                continue
            experiments[str(aggregate_id)] = {
                key: copy.deepcopy(raw.get(key))
                for key in (
                    "id",
                    "direction_id",
                    "package_id",
                    "scope_status",
                    "scope_version",
                    "scope_source",
                    "spec",
                )
                if raw.get(key) is not None
            }
        pending = []
        for proposal_id, raw in state["aggregates"]["proposal"].items():
            if not isinstance(raw, dict) or raw.get("disposition") != "PENDING":
                continue
            proposed = raw.get("proposed_node")
            matches = raw.get("node_id") == direction_id
            if isinstance(proposed, dict):
                matches = (
                    matches
                    or proposed.get("id") == direction_id
                    or direction_id in (proposed.get("parents") or [])
                )
            if matches:
                row = {
                    key: copy.deepcopy(raw.get(key))
                    for key in (
                        "id",
                        "level",
                        "node_id",
                        "disposition",
                        "proposed_node",
                    )
                    if raw.get(key) is not None
                }
                row.setdefault("id", str(proposal_id))
                pending.append(row)
        latest_direction_event = next(
            (
                str(event["event_id"])
                for event in reversed(events)
                if (
                    event.get("aggregate_type") == "direction"
                    and event.get("aggregate_id") == direction_id
                )
                or (
                    event.get("event_type") == "PackageActivated"
                    and isinstance(
                        event.get("payload", {}).get("scope_finalization"),
                        dict,
                    )
                    and event["payload"]["scope_finalization"]
                    .get("direction", {})
                    .get("aggregate_id")
                    == direction_id
                )
            ),
            "",
        )
        existing_package = state["aggregates"]["package"].get(package_id)
        draft_package = (
            copy.deepcopy(existing_package)
            if isinstance(existing_package, dict)
            and existing_package.get("lifecycle") == "DRAFT"
            else None
        )
        draft_binding_valid = False
        if source_package is not None and draft_package is not None:
            note = draft_package.get("document_note")
            current_binding = {
                "id": package_id,
                "draft_revision": draft_package.get("draftRevision"),
                "document_sha256": (
                    note.get("sha256") if isinstance(note, dict) else None
                ),
            }
            draft_binding_valid = (
                source_package == current_binding
                and source_package.get("id") == package_id
                and draft_package.get("draftStatus")
                in {"SCOPE_READY", "SCOPE_REVIEW"}
            )
        return self._stamp(
            state,
            {
                "direction": (
                    {
                        key: copy.deepcopy(direction.get(key))
                        for key in (
                            "id",
                            "level",
                            "status",
                            "version",
                            "spec",
                            "source",
                        )
                        if direction.get(key) is not None
                    }
                    if isinstance(direction, dict)
                    else None
                ),
                "experiments": experiments,
                "source_brainstorms": source_brainstorms,
                "source_brainstorm_ids": source_brainstorm_ids,
                "missing_source_brainstorms": missing_source_brainstorms,
                "source_proposal_id": source_proposal_id,
                "source_package": source_package,
                "draft_package": draft_package,
                "draft_binding_valid": draft_binding_valid,
                "pending": pending,
                "package_exists": existing_package is not None,
                "package_lifecycle": (
                    existing_package.get("lifecycle")
                    if isinstance(existing_package, dict)
                    else None
                ),
                "package_version": int(
                    state["aggregate_versions"].get(f"package/{package_id}", 0)
                ),
                "latest_direction_event_id": latest_direction_event,
            },
        )
