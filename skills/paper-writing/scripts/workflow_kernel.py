"""Stage 2 — domain-neutral workflow kernel: stage gates, profile resolution, paper plan."""

from __future__ import annotations

import argparse
from pathlib import Path

import common

# Domain-neutral lifecycle. Venue conventions live in profiles, never here.
STAGES = ["context", "plan", "section_drafts", "integration", "compression", "presubmission"]

# Default section order — the introduction-twice rule (first pass before evaluation).
SECTION_ORDER = [
    "introduction_first_pass",
    "evaluation",
    "method",
    "background",
    "related_work",
    "final_introduction",
    "abstract",
    "conclusion",
]

_SECTION_TITLES = {
    "introduction_first_pass": "Draft-0 Introduction",
    "evaluation": "Evaluation / Results",
    "method": "Method / Design",
    "background": "Background (if needed)",
    "related_work": "Related Work",
    "final_introduction": "Final Introduction",
    "abstract": "Abstract",
    "conclusion": "Conclusion",
}


def next_stage(done: list[str]) -> str | None:
    """Return the next lifecycle stage not yet completed, in order."""
    for stage in STAGES:
        if stage not in done:
            return stage
    return None


def is_legal_next(current: str, proposed: str) -> bool:
    """A stage transition is legal only to the immediately following stage."""
    if current not in STAGES or proposed not in STAGES:
        return False
    return STAGES.index(proposed) == STAGES.index(current) + 1


def resolve_profile(venue: str | None, root: Path | None = None) -> str:
    """Map a venue to a profile via config; unknown venues use the default profile."""
    cfg_root = (root or common.component_root())
    # config always ships with the component, not under a per-test root.
    cfg_dir = common.component_root() / "config"
    default = common.load_yaml(cfg_dir / "default_profile.yaml").get("default_profile", "ml_dl_general")
    if not venue:
        return default
    aliases = common.load_yaml(cfg_dir / "venue_aliases.yaml").get("aliases", {}) or {}
    return aliases.get(venue.strip().lower(), default)


def load_profile_text(profile: str) -> str:
    """Load a profile markdown file from the workflow kernel references."""
    path = common.component_root() / "references" / "workflow_kernel" / "profiles" / f"{profile}.md"
    return common.read_text(path)


def build_plan(paper_id: str, root: Path | None = None, profile: str | None = None) -> dict:
    """Emit context/paper_plan.md from context + the active profile; no corpus required."""
    home = common.project_dir(paper_id, root)
    spec = common.load_yaml(home / "paper.yaml")
    paper = spec.get("paper", {}) or {}
    claims = spec.get("claims", {}) or {}
    main_claims = claims.get("main", []) or []

    profile = profile or resolve_profile(paper.get("target_venue"), root)

    lines = [
        f"# Paper Plan: {paper.get('id', paper_id)}",
        "",
        f"- target venue: {paper.get('target_venue') or 'MISSING'}",
        f"- active profile: {profile}",
        f"- paper type: {paper.get('paper_type', '')}",
        f"- identity: {claims.get('identity', '')}",
        "",
        "## Section order (kernel)",
        "",
        "| Order | Section | Assigned claims |",
        "| --- | --- | --- |",
    ]
    # Map main claims onto the claim-bearing sections.
    claim_sections = {"introduction_first_pass", "evaluation", "final_introduction", "abstract"}
    claim_text = "; ".join(c.get("text", "") for c in main_claims) or "(none)"
    for i, key in enumerate(SECTION_ORDER, 1):
        assigned = claim_text if key in claim_sections else "-"
        lines.append(f"| {i} | {_SECTION_TITLES[key]} | {assigned} |")

    lines += [
        "",
        "## Notes",
        f"- Profile conventions sourced from `references/workflow_kernel/profiles/{profile}.md`.",
        "- Introduction is written twice: Draft-0 sets evaluation guardrails; Final is rewritten after results.",
    ]
    plan_text = "\n".join(lines) + "\n"
    plan_path = home / "context" / "paper_plan.md"
    common.write_text(plan_path, plan_text)
    return {"profile": profile, "sections": list(SECTION_ORDER), "plan_path": str(plan_path)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the paper plan from context + active profile.")
    ap.add_argument("paper_id")
    ap.add_argument("--profile", default=None)
    args = ap.parse_args()
    result = build_plan(args.paper_id, profile=args.profile)
    print(f"plan built with profile {result['profile']}: {result['plan_path']}")


if __name__ == "__main__":
    main()
