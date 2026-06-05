"""Skill validation oracles (plan §11.3). Pure: every oracle consumes injected evidence.

Pre-install stages (static / bundle / replay / adversarial / shadow / independent-review)
gate `candidate -> validated`. Runtime stages (installation / canary / continuous-monitor)
live in install.py / the worker. Effectiveness stays on measured oracles, never an LLM.
"""

from self_evolve import bundle, sandbox, schema

PRE_INSTALL_ORACLES = ("static_manifest", "bundle_integrity", "historical_replay",
                       "adversarial", "shadow", "independent_review")


def static_manifest(manifest):
    """Schema valid + bounded permissions + no trust-boundary write."""
    try:
        schema.validate_skill_manifest(manifest)
    except schema.SchemaViolation:
        return "fail"
    return "fail" if sandbox.permission_violations(manifest) else "pass"


def bundle_integrity(manifest, files):
    """Every file reproduces the manifest's sealed bundle_digest."""
    if files is None:
        return "inconclusive"
    return "pass" if bundle.verify_bundle(files, manifest.get("bundle_digest")) else "fail"


def historical_replay(report):
    """Required past workflows meet declared output/invariant thresholds."""
    if not report:
        return "inconclusive"
    req, passed = report.get("required", 0), report.get("passed", 0)
    return "pass" if req > 0 and passed == req else "fail"


def adversarial(report):
    """Independently generated attacks cannot break declared invariants."""
    if report is None:
        return "inconclusive"
    return "fail" if report.get("invariant_breaks") else "pass"


def shadow(report):
    """Candidate runs without authoritative effects and meets comparison thresholds."""
    if report is None:
        return "inconclusive"
    if report.get("scope_escape") or report.get("regressions"):
        return "fail"
    return "pass"


def independent_review(review):
    """Reviewer is not the proposer and found no unresolved issue (proposer != reviewer)."""
    if not review:
        return "inconclusive"
    if review.get("reviewer_id") and review.get("reviewer_id") == review.get("proposer_id"):
        return "fail"
    return "fail" if review.get("unresolved") else "pass"


def resolve_validation(results):
    """Map pre-install oracle results → 'validated' | 'rejected' | 'inconclusive'."""
    vals = list(results.values())
    if any(v == "fail" for v in vals):
        return "rejected"
    if all(results.get(name) == "pass" for name in PRE_INSTALL_ORACLES):
        return "validated"
    return "inconclusive"
