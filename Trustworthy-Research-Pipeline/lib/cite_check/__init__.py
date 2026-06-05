"""cite_check — fetch-don't-fabricate enforcement.

One deterministic resolve: every citation must resolve to a fetched source (R2). Anything that does
not resolve is returned so the caller can reject before write. The lib does no fetching itself — it
checks ids against the resolved set.
"""


def _unresolved(items, available, key):
    """Return the ids of items whose items[key] is not in the available set."""
    return [it["id"] for it in items if it.get(key) not in available]


def unresolved_citations(citations, source_ids):
    """R2: citation ids whose source_id does not resolve to a fetched source."""
    return _unresolved(citations, set(source_ids), "source_id")
