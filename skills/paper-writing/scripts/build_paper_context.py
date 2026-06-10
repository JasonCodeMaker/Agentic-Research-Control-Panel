"""Stage 1 — assemble the typed paper-context contracts from local evidence only."""

from __future__ import annotations

import argparse
from pathlib import Path

import common

# Canonical claim status values (SCREAMING_SNAKE).
CLAIM_STATUS = ("SUPPORTED", "PARTIAL", "MISSING", "OVERCLAIM")

# A claim's status can only be downgraded by evidence, never upgraded by the author.
_STATUS_RANK = {"SUPPORTED": 3, "PARTIAL": 2, "MISSING": 1, "OVERCLAIM": 0}


def _resolve(home: Path, ref: str) -> Path:
    """Resolve an evidence reference relative to the project home."""
    return home / ref


def _claim_status(home: Path, claim: dict) -> str:
    """Validate a claim against its evidence file; downgrade only, never upgrade."""
    declared = (claim.get("status") or "missing").upper()
    ref = claim.get("evidence")
    if not ref:
        return "MISSING"
    path = _resolve(home, ref)
    if not path.is_file():
        return "MISSING"
    value = claim.get("value")
    if value is not None and str(value) not in common.read_text(path):
        # Evidence exists but does not contain the declared number -> PARTIAL at best.
        return "PARTIAL" if _STATUS_RANK.get(declared, 0) > _STATUS_RANK["PARTIAL"] else declared
    return declared


def _collect_gaps(paper: dict, evidence: dict) -> list[str]:
    """Report missing target venue, baselines, and results — never invent them."""
    gaps = []
    if not paper.get("target_venue"):
        gaps.append("Missing target venue — required before venue adapter generation.")
    if not evidence.get("baselines"):
        gaps.append("Missing baselines — no baseline comparison declared.")
    if not evidence.get("results"):
        gaps.append("Missing results — no result artifact referenced.")
    return gaps


def _md_paper(paper: dict) -> str:
    return (
        "## Paper\n"
        f"- id: {paper.get('id', '')}\n"
        f"- title: {paper.get('title', '')}\n"
        f"- target venue: {paper.get('target_venue') or 'MISSING'}\n"
        f"- paper type: {paper.get('paper_type', '')}\n"
    )


def _md_claims(claims: dict, statuses: dict) -> str:
    lines = ["## Claims", f"- identity: {claims.get('identity', '')}", "", "### Main contribution claims"]
    for c in claims.get("main", []) or []:
        lines.append(f"- [{c['id']}] ({statuses.get(c['id'], 'MISSING')}) {c.get('text', '')}")
    lines.append("\n### Secondary contribution claims")
    for c in claims.get("secondary", []) or []:
        lines.append(f"- [{c['id']}] ({statuses.get(c['id'], 'MISSING')}) {c.get('text', '')}")
    lines.append("\n### Limitations / negative findings")
    for lim in claims.get("limitations", []) or []:
        lines.append(f"- {lim}")
    return "\n".join(lines) + "\n"


def _md_evidence(evidence: dict) -> str:
    lines = ["## Evidence"]
    lines.append("- result artifacts: " + ", ".join(evidence.get("results", []) or []))
    lines.append("- verified metrics:")
    for m in evidence.get("metrics", []) or []:
        lines.append(f"  - {m.get('name', '')} = {m.get('value', '')} (source: {m.get('source', '')})")
    lines.append("- baselines: " + ", ".join(evidence.get("baselines", []) or []))
    lines.append("- ablations: " + ", ".join(evidence.get("ablations", []) or []))
    lines.append("- datasets: " + ", ".join(evidence.get("datasets", []) or []))
    lines.append(f"- runtime provenance: {evidence.get('runtime_provenance', '')}")
    return "\n".join(lines) + "\n"


def _md_terminology(term: dict) -> str:
    lines = ["## Terminology"]
    lines.append(f"- method name: {term.get('method_name', '')}")
    lines.append("- module names: " + ", ".join(term.get("module_names", []) or []))
    lines.append("- metric names: " + ", ".join(term.get("metric_names", []) or []))
    lines.append("- dataset names: " + ", ".join(term.get("dataset_names", []) or []))
    lines.append("- forbidden synonyms: " + ", ".join(term.get("forbidden_synonyms", []) or []))
    lines.append("- citation keys: " + ", ".join(term.get("citation_keys", []) or []))
    return "\n".join(lines) + "\n"


def _md_claim_evidence_map(claims: dict, statuses: dict) -> str:
    rows = [
        "# Claim-Evidence Map",
        "",
        "| Claim | Evidence | Source | Status | Allowed wording |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in (claims.get("main", []) or []) + (claims.get("secondary", []) or []):
        status = statuses.get(c["id"], "MISSING")
        wording = c.get("wording", "bounded")
        if status in ("MISSING", "OVERCLAIM"):
            wording = "speculative-prohibited"
        elif status == "PARTIAL":
            wording = "bounded"
        rows.append(
            f"| {c.get('text', '')} | {c.get('evidence', '')} | {c.get('evidence', '')} "
            f"| {status} | {wording} |"
        )
    return "\n".join(rows) + "\n"


def _md_figures(figures: dict) -> str:
    lines = ["# Figure & Table Inventory", "", "## Existing"]
    for f in figures.get("existing", []) or []:
        lines.append(f"- {f.get('name', '')} ({f.get('kind', 'non-data')})")
    lines.append("\n## Missing")
    for f in figures.get("missing", []) or []:
        lines.append(f"- {f.get('name', '')} ({f.get('kind', 'non-data')})")
    return "\n".join(lines) + "\n"


def compute_statuses(paper_id: str, root: Path | None = None) -> tuple[dict, dict]:
    """Return ({claim_id: evidence-validated status}, claims-block) from paper.yaml."""
    home = common.project_dir(paper_id, root)
    spec = common.load_yaml(home / "paper.yaml")
    claims = spec.get("claims", {}) or {}
    statuses = {}
    for c in (claims.get("main", []) or []) + (claims.get("secondary", []) or []):
        statuses[c["id"]] = _claim_status(home, c)
    return statuses, claims


def build_context(paper_id: str, root: Path | None = None) -> dict:
    """Build paper_context.md, claim_evidence_map.md, figure_table_inventory.md, gap_report.md."""
    home = common.project_dir(paper_id, root)
    spec = common.load_yaml(home / "paper.yaml")
    paper = spec.get("paper", {}) or {}
    claims = spec.get("claims", {}) or {}
    evidence = spec.get("evidence", {}) or {}
    figures = spec.get("figures", {}) or {}
    terminology = spec.get("terminology", {}) or {}

    statuses, _ = compute_statuses(paper_id, root)
    gaps = _collect_gaps(paper, evidence)

    ctx = home / "context"
    context_md = (
        f"# Paper Context: {paper.get('id', paper_id)}\n\n"
        + _md_paper(paper) + "\n"
        + _md_claims(claims, statuses) + "\n"
        + _md_evidence(evidence) + "\n"
        + _md_figures(figures) + "\n"
        + _md_terminology(terminology)
    )
    if gaps:
        context_md += "\n## Gaps\n" + "\n".join(f"- {g}" for g in gaps) + "\n"

    common.write_text(ctx / "paper_context.md", context_md)
    common.write_text(ctx / "claim_evidence_map.md", _md_claim_evidence_map(claims, statuses))
    common.write_text(ctx / "figure_table_inventory.md", _md_figures(figures))
    gap_md = "# Gap Report\n\n" + ("\n".join(f"- {g}" for g in gaps) if gaps else "- No gaps detected.") + "\n"
    common.write_text(ctx / "gap_report.md", gap_md)

    return {"claim_status": statuses, "gaps": gaps, "context_dir": str(ctx)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the paper-context contracts from local inputs.")
    ap.add_argument("paper_id")
    args = ap.parse_args()
    result = build_context(args.paper_id)
    print(f"context built: {result['context_dir']}")
    if result["gaps"]:
        print("gaps:")
        for g in result["gaps"]:
            print(f"  - {g}")


if __name__ == "__main__":
    main()
