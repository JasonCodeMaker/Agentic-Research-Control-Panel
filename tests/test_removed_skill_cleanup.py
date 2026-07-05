from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REMOVED_PATHS = [
    "skills/paper-writing",
    "skills/research-lit",
    "skills/research-ideate",
    "skills/research-reflect",
    "skills/research-apply",
    "lib/cite_check",
    "skills/research-run/scripts/roles.py",
    "tests/cite_check",
    "tests/research-ideate",
    "tests/research-reflect",
    "tests/research-apply",
    "tests/research-run/test_roles.py",
]

REMOVED_TOKENS = [
    "paper-writing",
    "research-lit",
    "research-ideate",
    "research-reflect",
    "research-apply",
    "/research-lit",
    "/research-ideate",
    "/research-reflect",
    "/research-apply",
    "cite_check",
]

SCAN_ROOTS = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "workflow.ts",
    "lib",
    "skills",
    "tests",
]


def _candidate_files():
    for root_name in SCAN_ROOTS:
        root = ROOT / root_name
        if root.is_file():
            yield root
            continue
        if not root.exists():
            continue
        for path in root.rglob("*"):
            rel = path.relative_to(ROOT)
            rel_text = rel.as_posix()
            if not path.is_file():
                continue
            if rel_text == "tests/test_removed_skill_cleanup.py":
                continue
            if any(rel_text == p or rel_text.startswith(p + "/") for p in REMOVED_PATHS):
                continue
            if path.suffix not in {".md", ".py", ".ts", ".js", ".html"}:
                continue
            yield path


def test_removed_skill_paths_are_absent():
    present = [p for p in REMOVED_PATHS if (ROOT / p).exists()]
    assert present == []


def test_live_sources_do_not_reference_removed_skill_entrypoints():
    hits = []
    for path in _candidate_files():
        text = path.read_text(encoding="utf-8")
        for token in REMOVED_TOKENS:
            if token in text:
                hits.append(f"{path.relative_to(ROOT)}:{token}")
    assert hits == []
