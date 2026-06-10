"""Stage 4 — readability gate: only passing conversions enter style extraction."""

from __future__ import annotations

import re

# Canonical status values a converted source can receive.
CONVERSION_STATUS = ("CONVERTED_VERIFIED", "PARTIAL_CONVERSION", "CONVERSION_FAILED", "MANUAL_INPUT_REQUIRED")

CONVERTED_VERIFIED = "CONVERTED_VERIFIED"
PARTIAL_CONVERSION = "PARTIAL_CONVERSION"
CONVERSION_FAILED = "CONVERSION_FAILED"
MANUAL_INPUT_REQUIRED = "MANUAL_INPUT_REQUIRED"


def assess(md_text: str, source_kind: str = "paper", source_pages=None, md_pages=None) -> tuple[str, dict]:
    """Run the minimum readability checks and return (status, checks)."""
    low = md_text.lower()
    words = len(md_text.split())
    checks = {
        "not_near_empty": words >= 50,
        "has_heading": bool(re.search(r"^#", md_text, re.MULTILINE)),
        "has_abstract_or_intro": ("abstract" in low) or ("introduction" in low),
        "has_references": ("references" in low) or ("bibliography" in low),
        "no_corruption": md_text.count("�") <= 5,
    }
    if source_pages and md_pages:
        checks["page_count_plausible"] = abs(source_pages - md_pages) <= max(1, 0.3 * source_pages)

    if not checks["not_near_empty"] or not checks["has_heading"]:
        return CONVERSION_FAILED, checks
    if not checks["no_corruption"]:
        return CONVERSION_FAILED, checks
    if source_kind == "paper" and not checks["has_abstract_or_intro"]:
        return PARTIAL_CONVERSION, checks
    if checks.get("page_count_plausible") is False:
        return PARTIAL_CONVERSION, checks
    return CONVERTED_VERIFIED, checks
