"""Stage-2b: lib/cite_check — fetch-don't-fabricate (R2) + grounded-only claims (R6)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import cite_check  # noqa: E402


def test_r2_no_orphan_citations():
    citations = [{"id": "c1", "source_id": "s1"}, {"id": "c2", "source_id": "s2"}]
    assert cite_check.unresolved_citations(citations, {"s1", "s2"}) == []


def test_r2_orphan_citation_detected():
    citations = [{"id": "c1", "source_id": "s1"}, {"id": "c2", "source_id": "ghost"}]
    assert cite_check.unresolved_citations(citations, {"s1"}) == ["c2"]


def test_r6_every_claim_maps_to_verified_artifact():
    claims = [{"id": "k1", "artifact_id": "a1"}, {"id": "k2", "artifact_id": "a2"}]
    assert cite_check.ungrounded_claims(claims, {"a1", "a2"}) == []


def test_r6_ungrounded_claim_detected():
    claims = [{"id": "k1", "artifact_id": "a1"}, {"id": "k2", "artifact_id": "missing"}]
    assert cite_check.ungrounded_claims(claims, {"a1"}) == ["k2"]
