"""cite_check — fetch-don't-fabricate enforcement.

Two deterministic resolves: every citation must resolve to a fetched source (R2), and every paper
claim must map to a verified artifact (R6). Anything that does not resolve is returned so the caller
can reject before write. The lib does no fetching itself — it checks ids against the resolved set.
"""

import json
from pathlib import Path


def _unresolved(items, available, key):
    """Return the ids of items whose items[key] is not in the available set."""
    return [it["id"] for it in items if it.get(key) not in available]


def unresolved_citations(citations, source_ids):
    """R2: citation ids whose source_id does not resolve to a fetched source."""
    return _unresolved(citations, set(source_ids), "source_id")


def ungrounded_claims(claims, artifact_ids):
    """R6: paper claim ids that do not map to a verified artifact id (grounded-only)."""
    return _unresolved(claims, set(artifact_ids), "artifact_id")


def register_claims(claims_log, claims, artifact_ids):
    """R6 registry: append each claim only if every claim grounds to a verified artifact; else reject before write."""
    orphans = ungrounded_claims(claims, artifact_ids)
    if orphans:
        raise ValueError(f"ungrounded claims, registry write rejected: {orphans}")
    claims_log = Path(claims_log)
    claims_log.parent.mkdir(parents=True, exist_ok=True)
    with claims_log.open("a", encoding="utf-8") as f:
        for claim in claims:
            f.write(json.dumps(claim, ensure_ascii=False) + "\n")
    return claims
