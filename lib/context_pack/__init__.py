"""Deterministic, read-only Context Pack projection.

The pack is an ephemeral query result over management state.  It is never a
second store and is not an input to policy.  ``assemble`` remains a pure
function so callers can freeze the exact rendered JSON into a Run's
``context.json`` when execution begins.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

# Sections in canonical order. Scope intent and the learned-rule floor are
# protected: an agent should never lose the active objective, experiment gates, or
# proven failures because of a tight context budget.
PROTECTED_KEYS = (
    "project",
    "direction",
    "package_control",
    "experiments",
    "package_provenance",
    "pending_scope",
    "pending_decisions",
    "scope_warnings",
    "rules",
    "failed_methods",
)

# Canonical section key names (snake_case identifiers, not state-machine values — casing carve-out).
SECTION_KEYS = (
    "project",
    "direction",
    "package_control",
    "experiments",
    "package_provenance",
    "pending_scope",
    "pending_decisions",
    "scope_warnings",
    "rules",
    "learnings",
    "failed_methods",
    "adopted_wins",
    "papers_registry",
    "relationships",
    "open_gaps",
)


@dataclass
class Section:
    """One pack section: a titled list of evidence-linked lines."""
    key: str
    title: str
    lines: list
    protected: bool = False


@dataclass
class ContextPack:
    """The assembled pack: ordered sections + a provenance/faithfulness stamp."""
    sections: list
    stamp: dict = field(default_factory=dict)


def _metric_label(metric) -> str:
    if isinstance(metric, dict):
        name = metric.get("name", "")
        direction = metric.get("dir")
        return f"{name} ({direction})" if direction else (name or json.dumps(metric, sort_keys=True))
    if isinstance(metric, list):
        return ", ".join(str(m) for m in metric)
    return str(metric) if metric is not None else ""


def _baseline_label(baselines) -> str:
    if isinstance(baselines, list):
        return "; ".join(str(b) for b in baselines) if baselines else "unmeasured"
    return str(baselines) if baselines else "unmeasured"


def _list_label(items) -> str:
    if isinstance(items, list):
        return "; ".join(str(item) for item in items) if items else "unmeasured"
    return str(items) if items else "unmeasured"


def _project_section(node) -> Section | None:
    if not node:
        return None
    spec = node.get("spec", {})
    lines = []
    if spec.get("goal"):
        lines.append(f"- Goal: {spec['goal']}")
    if spec.get("contributions"):
        lines.append(f"- Contributions: {_list_label(spec['contributions'])}")
    if spec.get("out_of_scope"):
        lines.append(f"- Out of scope: {_list_label(spec['out_of_scope'])}")
    lines.append(f"- Source: scope node {node.get('id', '')}")
    return Section("project", "Active Project (spec)", lines, protected=True)


def _direction_section(node) -> Section | None:
    if not node:
        return None
    spec = node.get("spec", {})
    lines = []
    if spec.get("hypothesis"):
        lines.append(f"- Hypothesis: {spec['hypothesis']}")
    lines.append(f"- Metric: {_metric_label(spec.get('metric'))}")
    if spec.get("baselines"):
        lines.append(f"- Baselines: {_baseline_label(spec['baselines'])}")
    if spec.get("success_gate"):
        lines.append(f"- Success gate: {spec['success_gate']}")
    lines.append(f"- Source: scope node {node.get('id', '')}")
    return Section("direction", "Active Direction (spec)", lines, protected=True)


def _package_control_section(package) -> Section | None:
    if not package:
        return None
    lines = [f"- Package: {package.get('id', '')}"]
    for key in ("lifecycle", "phase", "blocker"):
        value = package.get(key)
        if value not in (None, "", []):
            lines.append(f"- {key}: {value}")
    return Section(
        "package_control",
        "Package execution boundary",
        lines,
        protected=True,
    )


def _experiments_section(nodes) -> Section | None:
    nodes = sorted(nodes or [], key=lambda n: n.get("id", ""))
    if not nodes:
        return None
    lines = []
    for node in nodes:
        spec = node.get("spec", {})
        bits = [
            f"purpose={spec.get('purpose', 'unmeasured')}",
            f"config_ref={spec.get('config_ref', 'unmeasured')}",
            f"gate={spec.get('gate', 'unmeasured')}",
            f"control_mode={spec.get('control_mode', 'unmeasured')}",
        ]
        lines.append(f"- {node.get('id', '')}: " + "; ".join(bits))
    return Section("experiments", "Experiments (ratified spec)", lines, protected=True)


def _package_provenance_section(provenance) -> Section | None:
    if not provenance:
        return None
    lines = []
    for key in ("sourceDirection", "sourceVersion", "sourceChange"):
        if provenance.get(key) not in (None, "", []):
            lines.append(f"- {key}: {provenance.get(key)}")
    source_experiments = provenance.get("sourceExperiments") or []
    if source_experiments:
        source_ids = [
            str(item.get("id", "")) if isinstance(item, dict) else str(item)
            for item in source_experiments
        ]
        lines.append(
            "- sourceExperiments: "
            + ", ".join(value for value in source_ids if value)
        )
    if not lines:
        return None
    return Section("package_provenance", "Package Scope provenance", lines, protected=True)


def _pending_scope_section(items) -> Section | None:
    items = sorted(items or [], key=lambda item: item.get("id", ""))
    if not items:
        return None
    lines = []
    for item in items:
        target = item.get("node_id") or (item.get("proposed_node") or {}).get("id") or "unknown"
        change = item.get("change") or item.get("rationale") or "pending Scope proposal"
        lines.append(
            f"- {item.get('id', '')}: unratified {item.get('level', 'scope')} proposal "
            f"for {target}; {change}"
        )
    return Section("pending_scope", "Pending Scope proposals (advisory)", lines, protected=True)


def _pending_decisions_section(items) -> Section | None:
    items = sorted(items or [], key=lambda item: item.get("id", ""))
    if not items:
        return None
    lines = []
    for item in items:
        outcome = (
            item.get("outcome")
            or item.get("route")
            or item.get("status")
            or "PENDING"
        )
        subject = item.get("subject_id") or item.get("package_id") or "unknown"
        lines.append(f"- {item.get('id', '')}: {outcome}; subject={subject}")
    return Section(
        "pending_decisions",
        "Pending Decisions",
        lines,
        protected=True,
    )


def _scope_warnings_section(warnings) -> Section | None:
    warnings = [str(w) for w in (warnings or []) if str(w).strip()]
    if not warnings:
        return None
    return Section("scope_warnings", "Scope warnings", [f"- {w}" for w in warnings], protected=True)


def _rules_section(learned_rules, analysis_rules) -> Section | None:
    lines = [f"- {b}" for b in learned_rules]
    for r in sorted(analysis_rules, key=lambda r: (r.get("pkg", ""), r.get("slug", ""))):
        anchor = f"packages/{r.get('pkg', '')}/analysis.html#rule-{r.get('slug', '')}"
        lines.append(f"- {r.get('prose', '')} — {anchor}")
    if not lines:
        return None
    return Section("rules", "Learned Rules (constraints)", lines, protected=True)


def _learnings_section(learnings) -> Section | None:
    lines = []
    for learning in sorted(learnings or [], key=lambda row: row.get("id", "")):
        text = (
            learning.get("observation")
            or learning.get("content")
            or learning.get("text")
            or learning.get("summary")
            or ""
        )
        evidence = learning.get("evidence_refs") or learning.get("evidenceRefs") or []
        refs = []
        for ref in evidence:
            if isinstance(ref, dict):
                refs.append(str(ref.get("uri") or ref.get("sha256") or ""))
            elif ref:
                refs.append(str(ref))
        suffix = f" — evidence: {', '.join(value for value in refs if value)}" if refs else ""
        lines.append(f"- [{learning.get('id', '')}] {text}{suffix}")
    if not lines:
        return None
    return Section("learnings", "Evidence-backed Learnings (non-binding)", lines, protected=False)


def _failed_methods_section(packages) -> Section | None:
    lines = []
    for pkg in sorted(packages, key=lambda p: p.get("id", "")):
        for m in pkg.get("methodsTried", []) or []:
            if m.get("verdict") in ("FAIL", "INCONCLUSIVE"):
                lines.append(
                    f"- [{pkg.get('id', '')}] {m.get('method', '')}: {m.get('hypothesis', '')} "
                    f"→ {m['verdict']} (gate {m.get('gate', '?')}, measured {m.get('measured', '?')}) "
                    f"— {m.get('evidencePath', '')}")
    if not lines:
        return None
    return Section("failed_methods", "Cross-package failed methods (do not repeat)", lines, protected=True)


def _adopted_wins_section(packages) -> Section | None:
    lines = []
    for pkg in sorted(packages, key=lambda p: p.get("id", "")):
        if pkg.get("category") != "success":
            continue
        for m in pkg.get("methodsTried", []) or []:
            if m.get("verdict") == "PASS":
                ev = pkg.get("adoptionPath") or m.get("evidencePath", "")
                lines.append(
                    f"- [{pkg.get('id', '')}] {m.get('method', '')}: {m.get('hypothesis', '')} → PASS — {ev}")
    if not lines:
        return None
    return Section("adopted_wins", "Adopted wins", lines, protected=False)


def _papers_registry_section(papers_registry) -> Section | None:
    lines = [f"- {p.get('title', '')} — {p.get('url', '')} [{p.get('id', '')}]"
             for p in papers_registry]
    if not lines:
        return None
    return Section("papers_registry", "Paper registry (cross-project)", lines, protected=False)


def _relationships_section(edges) -> Section | None:
    lines = []
    for e in edges:
        ev = f" — {e.get('evidence', '')}" if e.get("evidence") else ""
        lines.append(f"- {e.get('from', '')} --{e.get('type', '')}--> {e.get('to', '')}{ev}")
    if not lines:
        return None
    return Section("relationships", "Relationships (typed edges)", lines, protected=False)


def _open_gaps_section(gaps) -> Section | None:
    lines = [f"- [{g.get('id', '')}] {g.get('summary', '')} ({g.get('status', 'open')})" for g in gaps]
    if not lines:
        return None
    return Section("open_gaps", "Open gaps", lines, protected=False)


def _section_md(section: Section) -> str:
    return f"## {section.title}\n" + "\n".join(section.lines) + "\n"


def _truncate_section(section: Section, remaining: int) -> Section | None:
    """Fit as many whole lines as `remaining` chars allow; None if nothing fits."""
    marker = "...(truncated)"
    overhead = len(f"## {section.title}\n") + len(marker) + 2
    budget_for_lines = remaining - overhead
    if budget_for_lines <= 0:
        return None
    kept, used = [], 0
    for ln in section.lines:
        if used + len(ln) + 1 <= budget_for_lines:
            kept.append(ln)
            used += len(ln) + 1
        else:
            break
    if not kept:
        return None
    return Section(section.key, section.title, kept + [marker], protected=section.protected)


def _apply_budget(ordered, budget_chars):
    """Include the protected floor in full; add overlay sections in priority order
    until the budget is hit (snap-to-line truncation on the boundary section)."""
    floor = [s for s in ordered if s.protected]
    overlay = [s for s in ordered if not s.protected]
    included = list(floor)
    used = sum(len(_section_md(s)) for s in floor)
    truncated = False
    for s in overlay:
        block = _section_md(s)
        if used + len(block) <= budget_chars:
            included.append(s)
            used += len(block)
        else:
            truncated = True
            partial = _truncate_section(s, budget_chars - used)
            if partial is not None:
                included.append(partial)
            break
    return included, truncated


def assemble(inputs: dict, *, budget_chars: int = 8000) -> ContextPack:
    """Build a ContextPack from already-loaded stores. Pure + deterministic."""
    project = _project_section(inputs.get("project_node"))
    direction = _direction_section(inputs.get("direction_node"))
    package_control = _package_control_section(inputs.get("package"))
    experiments = _experiments_section(inputs.get("experiment_nodes", []))
    provenance = _package_provenance_section(inputs.get("package_provenance"))
    pending_scope = _pending_scope_section(inputs.get("pending_scope", []))
    pending_decisions = _pending_decisions_section(inputs.get("pending_decisions", []))
    warnings = _scope_warnings_section(inputs.get("scope_warnings", []))
    rules = _rules_section(inputs.get("learned_rules", []), inputs.get("analysis_rules", []))
    learnings = _learnings_section(inputs.get("learnings", []))
    failed = _failed_methods_section(inputs.get("packages", []))
    wins = _adopted_wins_section(inputs.get("packages", []))
    registry = _papers_registry_section(inputs.get("papers_registry", []))
    relationships = _relationships_section(inputs.get("edges", []))
    gaps = _open_gaps_section(inputs.get("gaps", []))

    ordered = [s for s in (
        project, direction, package_control, experiments, provenance,
        pending_scope, pending_decisions, warnings,
        rules, failed, learnings, wins, registry, relationships, gaps,
    )
               if s is not None]
    included, truncated = _apply_budget(ordered, budget_chars)

    sources_present = [s.key for s in ordered]
    package_provenance = inputs.get("package_provenance") or {}
    stamp = {
        "scope_version": inputs.get("scope_version", 0),
        "global_scope_version": inputs.get("global_scope_version", inputs.get("scope_version", 0)),
        "triage_version": inputs.get("triage_version", 0),
        "generated_at": inputs.get("generated_at", ""),
        "active_pkg": inputs.get("active_pkg"),
        "sourceDirection": package_provenance.get("sourceDirection"),
        "sourceVersion": package_provenance.get("sourceVersion"),
        "sourceChange": package_provenance.get("sourceChange"),
        "sourceExperiments": package_provenance.get(
            "sourceExperiments",
            [],
        ),
        "pendingScope": [item.get("id") for item in inputs.get("pending_scope", []) if item.get("id")],
        "source_seq": inputs.get("source_seq", 0),
        "source_hash": inputs.get("source_hash", ""),
        "budget_chars": budget_chars,
        "sources_present": sources_present,
        "truncated": truncated,
    }
    return ContextPack(sections=included, stamp=stamp)


def render_md(pack: ContextPack) -> str:
    """Agent-facing markdown render with stamp header."""
    s = pack.stamp
    out = ["# Context Pack",
           f"_source_seq={s.get('source_seq')} · source_hash={s.get('source_hash')} · "
           f"scope_version={s.get('scope_version')} · global_scope_version={s.get('global_scope_version')} · "
           f"generated_at={s.get('generated_at')} · "
           f"sources={','.join(s.get('sources_present', [])) or 'none'} · "
           f"truncated={s.get('truncated')}_"]
    out.append("")
    for sec in pack.sections:
        out.append(_section_md(sec).rstrip("\n"))
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def render_json(pack: ContextPack) -> dict:
    """Structured render — drives tests, consumers, and the human surface."""
    return {
        "stamp": pack.stamp,
        "sections": [
            {"key": s.key, "title": s.title, "protected": s.protected, "lines": list(s.lines)}
            for s in pack.sections
        ],
    }
