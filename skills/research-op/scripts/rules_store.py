"""rules.js store — the single rule registry (核心问题 #2).

Format: `window.RESEARCH_RULES = <json array>;` — JS-readable by the dashboard,
JSON-parseable here. This module is the only writer research-op ops use.
"""

import json
import re
from pathlib import Path

PREFIX = "window.RESEARCH_RULES = "
LEVELS = {"universal", "project", "package"}
KINDS = {"form", "trust", "constraint", "binding", "lesson"}
LEVEL_KINDS = {
    "universal": {"form", "trust"},
    "project": {"constraint"},
    "package": {"binding", "lesson"},
}
ORIGINS = {"mirror", "user", "apply", "selfevolve", "migration"}
STATUSES = {"ACTIVE", "RETIRED", "PROMOTED"}
REQUIRED = ("id", "level", "kind", "title", "source", "origin", "status", "addedAt")
HTML_TAG_RE = re.compile(r"<[^>]+>")


class RuleRowError(Exception):
    """A rule row violates the registry schema."""


def rules_path(root) -> Path:
    """data/rules.js under the dashboard root."""
    return Path(root) / "data" / "rules.js"


def load_rules(root) -> list:
    """Parse window.RESEARCH_RULES out of data/rules.js ([] if absent)."""
    p = rules_path(root)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8").strip()
    if not text.startswith(PREFIX):
        raise RuleRowError(f"{p} does not start with {PREFIX!r}")
    try:
        rows = json.loads(text[len(PREFIX):].rstrip(";"))
    except json.JSONDecodeError as e:
        raise RuleRowError(f"{p} has invalid JSON: {e}") from e
    if not isinstance(rows, list):
        raise RuleRowError(f"{p} must contain a JSON array")
    return rows


def validate_row(row: dict) -> None:
    """Reject a row missing required fields or carrying illegal enum/lifecycle values."""
    for f in REQUIRED:
        if not str(row.get(f, "")).strip():
            raise RuleRowError(f"rule row missing required field: {f}")
    if row["level"] not in LEVELS:
        raise RuleRowError(f"illegal level: {row['level']}")
    if row["kind"] not in KINDS:
        raise RuleRowError(f"illegal kind: {row['kind']}")
    if row["kind"] not in LEVEL_KINDS[row["level"]]:
        raise RuleRowError(f"kind {row['kind']} is not legal for level {row['level']}")
    if row["origin"] not in ORIGINS:
        raise RuleRowError(f"illegal origin: {row['origin']}")
    if row["status"] not in STATUSES:
        raise RuleRowError(f"illegal status: {row['status']}")
    if row["level"] in {"project", "package"}:
        for f in ("text", "rationale"):
            if not str(row.get(f, "")).strip():
                raise RuleRowError(f"{row['level']} rule row missing required field: {f}")
        if HTML_TAG_RE.search(str(row.get("text", ""))):
            raise RuleRowError("rule text must be plain prose, not HTML")
    if row["level"] == "package":
        if not str(row.get("pkg", "")).strip():
            raise RuleRowError("package-level rule needs pkg")
        if not row["id"].startswith(row["pkg"] + "#"):
            raise RuleRowError("package rule id must be <pkg>#<slug>")
    if row["status"] == "RETIRED" and not str(row.get("retireReason", "")).strip():
        raise RuleRowError("RETIRED rule needs retireReason")
    if row["status"] == "PROMOTED" and not str(row.get("promotedTo", "")).strip():
        raise RuleRowError("PROMOTED rule needs promotedTo")


def save_rules(root, rules: list) -> Path:
    """Validate every row + id uniqueness, then write data/rules.js."""
    seen = set()
    for row in rules:
        validate_row(row)
        if row["id"] in seen:
            raise RuleRowError(f"duplicate rule id: {row['id']}")
        seen.add(row["id"])
    p = rules_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(PREFIX + json.dumps(rules, indent=2, ensure_ascii=False) + ";\n",
                 encoding="utf-8")
    return p
