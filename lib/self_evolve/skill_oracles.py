"""Skill validation contract and locally exercised deterministic checks.

Pre-install reports for replay, adversarial, and shadow stages are produced by
the experiment workflow. This module names those required reports and resolves
their typed outcomes; it does not keep unused pseudo-runners for them.
"""

from self_evolve import bundle, sandbox, schema

PRE_INSTALL_ORACLES = ("static_manifest", "bundle_integrity", "historical_replay",
                       "adversarial", "shadow", "independent_review")

# Skill validation resolver outcomes (distinct from SKILL_STATES lifecycle states).
SKILL_VALIDATION_OUTCOMES = ("VALIDATED", "REJECTED", "INCONCLUSIVE")

ORACLE_PASS, ORACLE_FAIL, ORACLE_INCONCLUSIVE, ORACLE_ERROR = schema.ORACLE_RESULTS


def static_manifest(manifest):
    """Schema valid + bounded permissions + no trust-boundary write."""
    try:
        schema.validate_skill_manifest(manifest)
    except schema.SchemaViolation:
        return ORACLE_FAIL
    return ORACLE_FAIL if sandbox.permission_violations(manifest) else ORACLE_PASS


def bundle_integrity(manifest, files):
    """Every file reproduces the manifest's sealed bundle_digest."""
    if files is None:
        return ORACLE_INCONCLUSIVE
    return ORACLE_PASS if bundle.verify_bundle(files, manifest.get("bundle_digest")) else ORACLE_FAIL


def independent_review(review):
    """Reviewer is not the proposer and found no unresolved issue (proposer != reviewer)."""
    if not review:
        return ORACLE_INCONCLUSIVE
    if review.get("reviewer_id") and review.get("reviewer_id") == review.get("proposer_id"):
        return ORACLE_FAIL
    return ORACLE_FAIL if review.get("unresolved") else ORACLE_PASS


def resolve_validation(results):
    """Map pre-install oracle results → VALIDATED | REJECTED | INCONCLUSIVE."""
    vals = list(results.values())
    if any(v == ORACLE_FAIL for v in vals):
        return "REJECTED"
    if all(results.get(name) == ORACLE_PASS for name in PRE_INSTALL_ORACLES):
        return "VALIDATED"
    return "INCONCLUSIVE"
