"""Skill bundle digests (plan §9.2/§9.5/§11.3). Pure + deterministic.

A bundle is the set of files a Skill ships. Its digest is a content-addressed hash over the
sorted (name, per-file-sha256) pairs, so install/approval can bind to an exact bundle.
"""

import hashlib


def _sha(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def bundle_digest(files):
    """Deterministic digest over a {filename: content} mapping (order-independent)."""
    parts = [f"{name}:{_sha(content)}" for name, content in sorted(files.items())]
    return "sha256:" + hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def verify_bundle(files, expected_digest):
    """True iff the files reproduce the expected bundle digest."""
    return bundle_digest(files) == expected_digest


def permission_digest(permissions):
    """Stable digest of a permission set, for approval binding."""
    import json
    return "sha256:" + hashlib.sha256(
        json.dumps(permissions, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
