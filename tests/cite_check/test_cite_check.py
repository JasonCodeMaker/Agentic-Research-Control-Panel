"""Stage-2b: lib/cite_check — fetch-don't-fabricate (R2)."""

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
