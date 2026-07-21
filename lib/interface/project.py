"""Pure project-level view models for the browser interface."""

from __future__ import annotations

import copy
import html
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping

from lib.research_state.policy import STATES
from lib.research_state.schema import enum, load_schema, scope_contract


CATEGORIES = [
    {
        "id": "brainstorm",
        "title": "Brainstorm",
        "summary": (
            "Pre-package ideas (not packages, not in the SSOT). "
            "Convert one or more into a Direction + package."
        ),
        "href": "categories/brainstorm/",
    },
    {
        "id": "in-progress",
        "title": "In Progress",
        "summary": "Active packages with ongoing implementation, execution, or analysis.",
        "href": "categories/in-progress/",
    },
    {
        "id": "success",
        "title": "Success",
        "summary": "Packages adopted into the active project system.",
        "href": "categories/success/",
    },
    {
        "id": "fail",
        "title": "Fail",
        "summary": "Directions judged failed, stopped, or not promotable.",
        "href": "categories/fail/",
    },
]

TAG_ROLES = {
    "brainstorm": {
        "role": "optimization_direction",
        "label": "Optimization direction",
        "meaning": "The research or optimization direction this package explores.",
        "examples": ["metric contract", "data quality"],
    },
    "in-progress": {
        "role": "current_status",
        "label": "Current status",
        "meaning": "The current execution state or next active workflow status.",
        "examples": ["pilot running", "paused analysis"],
    },
    "success": {
        "role": "adapted_model_part",
        "label": "Adapted model part",
        "meaning": "The model or pipeline part adopted into the active project system.",
        "examples": ["export path", "quality gate"],
    },
    "fail": {
        "role": "failure_reason",
        "label": "Failure reason",
        "meaning": "The core technical reason the direction failed or was not promoted.",
        "examples": ["budget miss", "training collapse"],
    },
}

# These are browser presentation rules, not domain enums. All enum-valued arrays
# in schema.js are generated from lib/research_state/schema.json below.
STATUS_REQUIRED = {
    "in-progress": {
        "_all": ["activeGate", "primaryMetricVsGate", "nextRoute"],
        "_all_exempt": ["STOPPED"],
        "EXPERIMENT_RUNNING": ["openRuns"],
        "LIVE_ANALYSIS": ["openRuns", "lastAction"],
        "BLOCKED": ["currentBlocker"],
        "NEXT_ACTION_READY": ["lastDecision", "lastDecisionEvidencePath"],
        "STOPPED": ["terminationMessage"],
    },
    "success": {
        "_all": ["terminationMessage", "methodsTried", "adoptionPath"],
        "WIN_SUPERSEDED": ["supersededBy"],
    },
    "fail": {
        "_all": ["terminationMessage", "methodsTried"],
        "ARCHIVED_CONDITIONAL": ["reopenTrigger"],
    },
}

STATUS_DESCRIPTIONS = {
    "in-progress": (
        "Active packages. Must declare the active gate, primary metric vs gate, "
        "and next route at all times (STOPPED is terminal-within-lane and is "
        "exempt from that trio)."
    ),
    "success": (
        "Packages adopted into the active project. Must carry the structured "
        "methodsTried log, termination message, and adoption path."
    ),
    "fail": (
        "Directions judged failed. Must carry the structured methodsTried log "
        "and a one-sentence termination message; conditionally-reopenable rows "
        "must declare the reopen trigger."
    ),
}

STATUS_FAMILY = {
    "CONTEXT_LOADED": "work",
    "IMPLEMENTING": "work",
    "IMPLEMENTATION_REVIEW": "work",
    "READY_TO_LAUNCH": "launch",
    "EXPERIMENT_RUNNING": "live",
    "LIVE_ANALYSIS": "live",
    "RESULT_ANALYSIS": "analyze",
    "NEXT_ACTION_READY": "analyze",
    "BLOCKED": "stop",
    "DECISION_ADJUDICATION": "analyze",
    "STOPPED": "stop",
    "ADOPTED_UNCONFIRMED": "WIN_UNCONFIRMED",
    "ADOPTED": "win",
    "WIN_SUPERSEDED": "WIN_SUPERSEDED",
    "ARCHIVED": "stop",
    "ARCHIVED_CONDITIONAL": "ARCHIVED_CONDITIONAL",
}

# These values describe the frozen browser presentation, not Scope validation.
# Field membership, kinds, word bounds, enum values, and reading-field
# exclusions are always projected from lib/research_state/schema.json.
_SCOPE_LEVEL_PRESENTATION_ORDER = ("direction", "project", "experiment")
_SCOPE_FIELD_LABEL_OVERRIDES = {
    "config_ref": "Config",
    "purpose": "Experiment",
}
_SCOPE_REJECTED_LEGACY_FIELDS = ("yardstick", "provenance")
_SCOPE_KIND_TO_BROWSER_KIND = {
    "scalar_text": "text",
    "list_text": "list",
    "reference": "ref",
    "metric": "metric",
    "enum": "enum",
}

NEXT_ROUTE_MEANING = {
    "RUN_NEXT_EXPERIMENT": "Use when the active plan defines the next run.",
    "FIX_IMPLEMENTATION": "Use for concrete code or artifact issues.",
    "REVISE_PLAN": "Use when the executable plan changes.",
    "TERMINATE": "Use when evidence says the direction should stop or archive.",
    "ASK_USER": "Use when a user-level decision blocks progress.",
}

CONTRIBUTION_SPINE = [
    {"id": "multi-view-encoder", "label": "Multi-view video encoder"},
    {"id": "progressive-cotraining", "label": "Progressive end-to-end co-training"},
    {"id": "contrastive-plus-main", "label": "Contrastive pre-train + main stage"},
    {
        "id": "stage1-handoff",
        "label": "Stage-1 to Stage-2 handoff (inference selector)",
    },
    {"id": "evaluation-contract", "label": "Evaluation / measurement contract"},
    {"id": "none", "label": "Outside the contribution spine"},
]

METHODS_TRIED_FIELDS = [
    "method",
    "hypothesis",
    "gate",
    "measured",
    "verdict",
    "evidencePath",
]

RULE_CARD_RE = re.compile(
    r'data-rule="([RT]\d+)"[^>]*data-kind="([^"]+)"'
    r'[\s\S]*?<h3 class="title">([^<]+)</h3>'
)
RULE_FILE_KIND = {
    "html-rules.html": "form",
    "trustworthy-research-rules.html": "trust",
}

RUN_STATUS_COMPAT = {
    "QUEUED": "QUEUED",
    "RUNNING": "RUNNING",
    "STALE": "STALE",
    "COMPLETED": "COMPLETED",
    "FAILED": "RUN_FAILED",
    "HALTED": "RUN_HALTED",
    "SKIPPED": "SKIPPED",
}


@dataclass(frozen=True)
class ScopeProjection:
    """Legacy-compatible browser projection of structured scope aggregates."""

    nodes: dict[str, dict[str, Any]]
    transitions: list[dict[str, Any]]
    triage: list[dict[str, Any]]


def _bucket(state: Mapping[str, Any], aggregate_type: str) -> Mapping[str, Any]:
    aggregates = state.get("aggregates", {})
    bucket = aggregates.get(aggregate_type, {}) if isinstance(aggregates, Mapping) else {}
    return bucket if isinstance(bucket, Mapping) else {}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def render_global(name: str, value: Any) -> str:
    """Render one deterministic browser global."""
    return f"window.{name} = {_json(value)};\n"


def project_profile(state: Mapping[str, Any]) -> dict[str, Any]:
    projects = _bucket(state, "project")
    if not projects:
        return {}
    project_id = sorted(str(key) for key in projects)[0]
    record = projects[project_id]
    if not isinstance(record, Mapping):
        return {}
    spec = record.get("spec") if isinstance(record.get("spec"), Mapping) else {}
    explicit = record.get("interface_profile")
    if not isinstance(explicit, Mapping):
        explicit = record.get("profile")
    profile = copy.deepcopy(dict(explicit)) if isinstance(explicit, Mapping) else {}
    profile.setdefault(
        "title",
        record.get("title") or record.get("name") or project_id.removeprefix("project/"),
    )
    profile.setdefault(
        "summary",
        record.get("summary") or spec.get("goal") or record.get("goal") or "",
    )
    profile.setdefault(
        "currentQuestion",
        record.get("currentQuestion")
        or record.get("current_question")
        or spec.get("current_question")
        or spec.get("goal")
        or "",
    )
    return profile


def universal_rule_rows(rule_sources: Mapping[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in ("html-rules.html", "trustworthy-research-rules.html"):
        text = rule_sources.get(name, "")
        kind = RULE_FILE_KIND[name]
        for rule_id, _card_kind, title in RULE_CARD_RE.findall(text):
            rows.append(
                {
                    "id": rule_id,
                    "level": "universal",
                    "kind": kind,
                    "title": title.strip(),
                    "source": f"rules/{name}#{rule_id}",
                    "origin": "mirror",
                    "status": "ACTIVE",
                    "addedAt": "bundled",
                }
            )
    return rows


def rule_views(
    state: Mapping[str, Any],
    *,
    bundled: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Return one browser registry; state rows override bundled mirrors by id."""
    by_id: dict[str, dict[str, Any]] = {}
    for row in bundled:
        rule_id = row.get("id")
        if rule_id:
            by_id[str(rule_id)] = copy.deepcopy(dict(row))
    for rule_id, row in _bucket(state, "rule").items():
        if not isinstance(row, Mapping):
            continue
        projected = copy.deepcopy(dict(row))
        projected.setdefault("id", str(rule_id))
        by_id[str(projected["id"])] = projected
    for learning_id, row in _bucket(state, "learning").items():
        if not isinstance(row, Mapping):
            continue
        projected = copy.deepcopy(dict(row))
        projected.setdefault("id", str(learning_id))
        projected.setdefault("kind", "lesson")
        projected.setdefault("level", "package" if projected.get("package_id") else "project")
        projected.setdefault("status", "ACTIVE")
        by_id.setdefault(str(projected["id"]), projected)
    return [by_id[key] for key in sorted(by_id)]


def brainstorm_views(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for brainstorm_id, row in _bucket(state, "brainstorm").items():
        if not isinstance(row, Mapping):
            continue
        projected = copy.deepcopy(dict(row))
        projected.setdefault("id", str(brainstorm_id))
        if not projected.get("detailPath") and projected.get("legacy_detail_path"):
            projected["detailPath"] = projected["legacy_detail_path"]
        if not projected.get("detailPath"):
            created = str(projected.get("created_at") or "")
            date_prefix = created[:10] + "-" if re.match(r"^\d{4}-\d{2}-\d{2}", created) else ""
            projected["detailPath"] = (
                f"brainstorm/{date_prefix}{projected['id']}.html"
            )
        rows.append(projected)
    return sorted(rows, key=lambda row: str(row.get("id", "")))


def _brainstorm_detail_path(record: Mapping[str, Any]) -> str:
    raw = str(record.get("detailPath") or "")
    relative = PurePosixPath(raw)
    if (
        relative.is_absolute()
        or len(relative.parts) != 2
        or relative.parts[0] != "brainstorm"
        or relative.parts[1] in {"", ".", ".."}
        or relative.suffix.lower() != ".html"
    ):
        raise ValueError(f"unsafe brainstorm detailPath: {raw!r}")
    return relative.as_posix()


def render_brainstorm_page(record: Mapping[str, Any]) -> str:
    """Render the existing compact brainstorm detail layout from one aggregate."""
    idea_id = html.escape(str(record.get("id") or ""), quote=True)
    title = html.escape(str(record.get("title") or idea_id), quote=True)
    idea = html.escape(str(record.get("idea") or ""), quote=True)
    rough_metric = html.escape(
        str(record.get("rough_metric") or "Not specified yet"), quote=True
    )
    created = html.escape(str(record.get("created_at") or "")[:10], quote=True)
    language = html.escape(str(record.get("page_language") or "en"), quote=True)
    refs = record.get("lit_refs") if isinstance(record.get("lit_refs"), list) else []
    if refs:
        refs_html = "\n".join(
            f"              <li>{html.escape(str(ref), quote=True)}</li>"
            for ref in refs
        )
    else:
        refs_html = (
            '              <li class="muted">'
            "No literature grounding recorded yet.</li>"
        )
    date_label = f" - {created}" if created else ""
    return f"""<!doctype html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Brainstorm - {title}</title>
  <link rel="stylesheet" href="../assets/research.css">
  <style>
    .callout {{ border-left: 4px solid var(--clay); background: #fbf4ea; padding: 12px 16px; margin: 16px 0; font-size: 14px; }}
    .callout.note {{ border-left-color: #56708e; background: #eef2f8; }}
    .tagline {{ color: var(--g500); font-family: var(--mono); font-size: 11px; letter-spacing: 0.10em; text-transform: uppercase; }}
    .field-grid {{ display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 12px 18px; margin-top: 16px; }}
    .field-grid dt {{ color: var(--g500); font-family: var(--mono); font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; }}
    .field-grid dd {{ margin: 0; color: var(--slate); }}
    .muted {{ color: var(--g500); font-style: italic; }}
    @media (max-width: 720px) {{ .field-grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body data-page="brainstorm">
  <div class="shell">
    <div class="callout note" style="margin:0 0 18px;">
      <span class="tagline">pre-package idea{date_label}</span>
      <p style="margin:6px 0 0;">This is an automatically generated brainstorm page. It is readable by default, but it is not a ratified Direction, not a package, and not an SSOT change.</p>
    </div>

    <header class="masthead" data-section="masthead">
      <div class="eyebrow">Brainstorm &middot; pre-package idea</div>
      <h1>{title}</h1>
      <p class="lead">{idea}</p>
      <div class="toolbar">
        <a class="pill" href="../categories/brainstorm/index.html">Brainstorm lane</a>
        <a class="pill" href="../index.html">Dashboard</a>
      </div>
    </header>

    <main>
      <section data-section="idea">
        <article class="module-card">
          <h2>Idea Snapshot</h2>
          <dl class="field-grid">
            <dt>Idea ID</dt>
            <dd><code>{idea_id}</code></dd>
            <dt>Rough metric</dt>
            <dd>{rough_metric}</dd>
            <dt>Grounding</dt>
            <dd>
              <ul style="margin:0; padding-left:18px;">
{refs_html}
              </ul>
            </dd>
            <dt>Next decision</dt>
            <dd>Shape this hunch into a typed spec only when the user is ready: <code>{{hypothesis, metric, baselines, success_gate}}</code>. Submit any Direction through Triage; do not commit the SSOT from this page.</dd>
          </dl>
        </article>
      </section>
    </main>
  </div>
</body>
</html>
"""


def brainstorm_pages(rows: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    pages: dict[str, str] = {}
    for record in rows:
        relative = _brainstorm_detail_path(record)
        if relative in pages:
            raise ValueError(f"duplicate brainstorm detailPath: {relative}")
        pages[relative] = render_brainstorm_page(record)
    return pages


def _scope_node(
    aggregate_type: str,
    aggregate_id: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    if record.get("level") in {"project", "direction"}:
        node = copy.deepcopy(dict(record))
        node.pop("_scope_transition", None)
        node.pop("_legacy_transition", None)
        node.setdefault("id", aggregate_id)
        node.setdefault("parents", [])
        node.setdefault("status", "ACTIVE")
        node.setdefault("version", 1)
        return node

    spec = record.get("spec") if isinstance(record.get("spec"), Mapping) else {}
    if aggregate_type == "project":
        node_spec = copy.deepcopy(dict(spec))
        for key in ("goal", "contributions", "out_of_scope"):
            if key not in node_spec and key in record:
                node_spec[key] = copy.deepcopy(record[key])
        return {
            "id": aggregate_id,
            "level": "project",
            "parents": copy.deepcopy(record.get("parents") or []),
            "source": record.get("source", "research-state"),
            "spec": node_spec,
            "status": record.get("scope_status", "ACTIVE"),
            "version": record.get("version", 1),
        }

    if aggregate_type == "direction":
        parents = copy.deepcopy(record.get("parents") or [])
        if not parents and record.get("project_id"):
            parents = [record["project_id"]]
        return {
            "id": aggregate_id,
            "level": "direction",
            "parents": parents,
            "source": record.get("source", "research-state"),
            "spec": copy.deepcopy(dict(spec)),
            "status": record.get("scope_status", "ACTIVE"),
            "version": record.get("version", 1),
        }

    parents = copy.deepcopy(record.get("parents") or [])
    if not parents and record.get("direction_id"):
        parents = [record["direction_id"]]
    return {
        "id": aggregate_id,
        "level": "experiment",
        "parents": parents,
        "source": record.get("scope_source")
        or record.get("source", "research-state"),
        "spec": copy.deepcopy(dict(spec)),
        "status": record.get("scope_status", "ACTIVE"),
        "version": record.get("scope_version") or record.get("version", 1),
    }


def _historical_scope_node(
    aggregate_type: str,
    aggregate_id: str,
    transition: Mapping[str, Any],
    fallback: Mapping[str, Any],
) -> dict[str, Any]:
    """Project a migrated Task snapshot as its canonical Experiment history."""
    legacy = transition.get("node")
    if not isinstance(legacy, Mapping):
        return copy.deepcopy(dict(fallback))
    if aggregate_type != "experiment":
        return _scope_node(aggregate_type, aggregate_id, legacy)
    legacy_spec = (
        legacy.get("spec")
        if isinstance(legacy.get("spec"), Mapping)
        else {}
    )
    canonical_spec = {
        "purpose": legacy_spec.get("purpose")
        or legacy_spec.get("experiment")
        or "",
        "config_ref": legacy_spec.get("config_ref")
        or legacy_spec.get("config")
        or "",
        "gate": legacy_spec.get("gate") or "",
        "control_mode": legacy_spec.get("control_mode") or "",
    }
    parents = copy.deepcopy(legacy.get("parents") or [])
    return {
        "id": aggregate_id,
        "level": "experiment",
        "parents": parents,
        "source": legacy.get("source", "legacy-migration"),
        "spec": canonical_spec,
        "status": legacy.get("status", "ACTIVE"),
        "version": legacy.get("version", 1),
    }


def scope_projection(state: Mapping[str, Any]) -> ScopeProjection:
    nodes: dict[str, dict[str, Any]] = {}
    transitions: list[dict[str, Any]] = []
    for aggregate_type in ("project", "direction", "experiment"):
        for aggregate_id, raw in sorted(
            _bucket(state, aggregate_type).items(), key=lambda item: str(item[0])
        ):
            if not isinstance(raw, Mapping):
                continue
            if aggregate_type == "experiment":
                formal_scope_experiment = (
                    raw.get("direction_id")
                    and raw.get("scope_version")
                    and raw.get("scope_source")
                )
                if not formal_scope_experiment and (
                    raw.get("package_id") not in (None, "")
                    or not (raw.get("direction_id") or raw.get("parents"))
                ):
                    # Retain migration compatibility for old execution-only
                    # rows, but a bound formal Experiment remains a Scope node:
                    # package binding does not create or hide a second object.
                    continue
            node = _scope_node(aggregate_type, str(aggregate_id), raw)
            node_id = str(node["id"])
            nodes[node_id] = node
            legacy_history = raw.get("legacy_transitions")
            if isinstance(legacy_history, list) and legacy_history:
                transition_rows = [
                    copy.deepcopy(dict(item))
                    for item in legacy_history
                    if isinstance(item, Mapping)
                ]
            else:
                transition = raw.get("_scope_transition")
                if not isinstance(transition, Mapping):
                    transition = raw.get("_legacy_transition")
                transition_rows = [
                    copy.deepcopy(dict(transition))
                    if isinstance(transition, Mapping)
                    else {}
                ]
            for row in transition_rows:
                historical_node = _historical_scope_node(
                    aggregate_type,
                    node_id,
                    row,
                    node,
                )
                row = {
                    key: value
                    for key, value in row.items()
                    if value is not None and key != "node"
                }
                row.setdefault(
                    "transaction_id",
                    f"projection:{aggregate_type}:{aggregate_id}:"
                    f"{historical_node.get('version', 1)}",
                )
                row.setdefault(
                    "scope_version",
                    historical_node.get("version", 1),
                )
                row.setdefault("op", "project")
                row["node_id"] = node_id
                row["node"] = historical_node
                transitions.append(row)

    triage: list[dict[str, Any]] = []
    for proposal_id, raw in sorted(
        _bucket(state, "proposal").items(), key=lambda item: str(item[0])
    ):
        if not isinstance(raw, Mapping):
            continue
        row = copy.deepcopy(dict(raw))
        row.setdefault("id", str(proposal_id))
        disposition = str(row.get("disposition") or row.get("status") or "PENDING")
        row["status"] = disposition.lower()
        triage.append(row)
    return ScopeProjection(nodes=nodes, transitions=transitions, triage=triage)


def _status_schema() -> dict[str, Any]:
    available = set(enum("package_status_compat"))
    return {
        category: {
            "states": [status for status in statuses if status in available],
            "description": STATUS_DESCRIPTIONS[category],
            "required": STATUS_REQUIRED[category],
            "forbidden": [],
        }
        for category, statuses in STATES.items()
    }


def _scope_field_label(field: str) -> str:
    return _SCOPE_FIELD_LABEL_OVERRIDES.get(
        field,
        field.replace("_", " ").capitalize(),
    )


def scope_browser_schema() -> dict[str, Any]:
    """Project the central Scope contract into the frozen browser shape."""
    contract = scope_contract()
    specs = contract["specs"]
    level_order = [
        level
        for level in _SCOPE_LEVEL_PRESENTATION_ORDER
        if level in specs
    ]
    level_order.extend(
        level for level in specs if level not in level_order
    )

    levels: dict[str, Any] = {}
    for level in level_order:
        source_fields = specs[level]["fields"]
        ordered = list(source_fields)
        primary = ordered[:1]
        primary.extend(
            field
            for field, field_contract in source_fields.items()
            if field_contract["kind"] in {"metric", "enum"}
            and field not in primary
        )

        fields: dict[str, Any] = {}
        for field in sorted(
            source_fields,
            key=lambda candidate: (_scope_field_label(candidate).casefold(), candidate),
        ):
            source = source_fields[field]
            kind = source["kind"]
            entry: dict[str, Any] = {
                "kind": _SCOPE_KIND_TO_BROWSER_KIND[kind],
                "label": _scope_field_label(field),
            }
            if kind in {"scalar_text", "list_text", "metric"}:
                entry["maxWords"] = int(source["max_words"])
                entry["minWords"] = int(source["min_words"])
            if kind == "enum":
                entry["values"] = sorted(enum(str(source["enum"])))
            fields[field] = entry

        levels[level] = {
            "fields": fields,
            "order": ordered,
            "primary": primary,
        }

    return {
        "levels": levels,
        "oldNodeFields": list(_SCOPE_REJECTED_LEGACY_FIELDS),
        "readingFields": sorted(str(field) for field in contract["reading_fields"]),
    }


def render_scope_schema_js() -> str:
    """Generate the Scope Inspector field contract from schema.json."""
    data = json.dumps(
        scope_browser_schema(),
        ensure_ascii=False,
        indent=2,
    )
    return (
        '"use strict";\n'
        "// Generated from lib/research_state/schema.json; do not hand-edit field rules.\n"
        "(function (root) {\n"
        "  root.SCOPE_SCHEMA = "
        + data.replace("\n", "\n  ")
        + ";\n"
        "})(typeof window !== \"undefined\" ? window : globalThis);\n"
    )


def render_schema_js() -> str:
    """Generate browser enum globals directly from the central JSON schema."""
    schema = load_schema()
    # Touch the compatibility block too: generation should fail if the schema
    # ceases to expose the canonical compatibility contract.
    if not isinstance(schema.get("compatibility"), dict):
        raise ValueError("research-state schema has no compatibility map")
    blocks = [
        "// Generated from lib/research_state/schema.json; do not hand-edit enums.\n",
        render_global("RESEARCH_STATE_ENUMS", schema["enums"]),
        render_global("RESEARCH_STATE_COMPATIBILITY", schema["compatibility"]),
        render_global("RESEARCH_STATUS_SCHEMA", _status_schema()),
        render_global("RESEARCH_CONTRIBUTION_SPINE", CONTRIBUTION_SPINE),
        render_global("EXPERIMENT_VERDICT", list(enum("result_verdict"))),
        render_global("RESULT_VALIDITY", list(enum("result_validity"))),
        render_global("NEXT_ROUTE", list(enum("decision_route"))),
        render_global(
            "NEXT_ROUTE_MEANING",
            {
                route: NEXT_ROUTE_MEANING.get(route, "")
                for route in enum("decision_route")
            },
        ),
        render_global("RESEARCH_METHODS_TRIED_FIELDS", METHODS_TRIED_FIELDS),
        render_global(
            "RESEARCH_STATUS_FAMILY",
            {
                status: STATUS_FAMILY.get(status, "unknown")
                for status in enum("package_status_compat")
            },
        ),
    ]
    return "".join(blocks)


def render_project_js(
    state: Mapping[str, Any],
    packages: list[dict[str, Any]],
) -> str:
    return "\n".join(
        [
            render_global("RESEARCH_PROJECT_PROFILE", project_profile(state)).rstrip(),
            render_global("RESEARCH_CATEGORIES", CATEGORIES).rstrip(),
            render_global("RESEARCH_TAG_ROLES", TAG_ROLES).rstrip(),
            render_global("RESEARCH_PACKAGES", packages).rstrip(),
            "",
        ]
    )


def render_jsonl(rows: Iterable[Mapping[str, Any]]) -> str:
    return "".join(
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for row in rows
    )


def project_run_record(run_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    status = str(record.get("status") or "QUEUED")
    compatible = RUN_STATUS_COMPAT.get(status, status)
    terminal = compatible in {"COMPLETED", "RUN_FAILED", "RUN_HALTED", "SKIPPED"}
    return {
        **copy.deepcopy(dict(record)),
        "op": "terminal" if terminal else "launched",
        "run_id": run_id,
        "pkg": record.get("package_id") or record.get("pkg"),
        "exp_id": record.get("experiment_id") or record.get("exp_id"),
        "final_status": compatible if terminal else None,
        "terminal": terminal,
    }


def live_run_views(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project management-open Runs plus explicit terminal history.

    ``open_runs`` is the discovery projection maintained by the reducer.
    Terminal rows are then joined from their canonical Run aggregates for the
    frozen interface's recent-history rail. A non-terminal aggregate absent
    from ``open_runs`` is never rediscovered merely because it still exists.
    """
    aggregate_runs = _bucket(state, "run")
    open_runs = state.get("open_runs", {})
    if not isinstance(open_runs, Mapping):
        raise ValueError("state.open_runs must be an object")
    rows: list[dict[str, Any]] = []
    for run_id, open_record in sorted(
        open_runs.items(), key=lambda item: str(item[0])
    ):
        run_id = str(run_id)
        record = aggregate_runs.get(run_id)
        if not isinstance(open_record, Mapping) or not isinstance(record, Mapping):
            raise ValueError(
                f"open run index references a missing Run aggregate: {run_id}"
            )
        rows.append(
            project_run_record(
                run_id,
                {**copy.deepcopy(dict(record)), **copy.deepcopy(dict(open_record))},
            )
        )
    open_ids = {str(run_id) for run_id in open_runs}
    for run_id, record in sorted(
        aggregate_runs.items(), key=lambda item: str(item[0])
    ):
        run_id = str(run_id)
        if run_id in open_ids or not isinstance(record, Mapping):
            continue
        projected = project_run_record(run_id, record)
        if projected["terminal"]:
            rows.append(projected)
    return sorted(rows, key=lambda row: str(row["run_id"]))


def acknowledged_run_ids(state: Mapping[str, Any]) -> list[str]:
    return sorted(
        str(run_id)
        for run_id, record in _bucket(state, "run").items()
        if isinstance(record, Mapping) and record.get("attention_acknowledged")
    )
