"""Sandbox boundary policy for generated Skills (plan §12.1). Pure: deny-by-default checks.

A candidate's declared permissions must stay inside the sandbox and must never touch the
trust-boundary surfaces (`.claude/skills/`, validators, policies, authoritative stores).
"""

SANDBOX_TOKEN = "sandboxes/"

# Substrings that must never appear in a generated Skill's write_roots (trust boundary, §12.1/D6).
FORBIDDEN_WRITE_TOKENS = (
    ".claude/skills", "rules/releases", "rules/transitions", "skills/releases",
    "skills/transitions", "approvals", "/validators", "/policies", "budget",
    "current-state.json", "/lib/",
)


def permission_violations(manifest):
    """Return a list of boundary violations (empty = sandbox-safe)."""
    perms = manifest.get("permissions", {})
    v = []
    if perms.get("network", "deny") != "deny":
        v.append("network-not-denied")
    if perms.get("credentials", "deny") != "deny":
        v.append("credentials-not-denied")
    tools = perms.get("tools")
    if not tools or "*" in tools:
        v.append("tools-unbounded")
    write_roots = perms.get("write_roots", [])
    if not write_roots:
        v.append("no-write-roots")
    for w in write_roots:
        if SANDBOX_TOKEN not in w:
            v.append(f"write-root-outside-sandbox:{w}")
        if any(tok in w for tok in FORBIDDEN_WRITE_TOKENS):
            v.append(f"forbidden-write:{w}")
    return v


def is_sandbox_safe(manifest):
    """True iff the manifest declares no boundary-violating permission."""
    return not permission_violations(manifest)
