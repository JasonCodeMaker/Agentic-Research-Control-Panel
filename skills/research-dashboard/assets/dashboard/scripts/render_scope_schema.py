#!/usr/bin/env python3
"""Render the browser Scope schema from lib.scope_ssot."""

import argparse
import json
import os
import sys
from pathlib import Path

def _candidate_roots() -> list[Path]:
    here = Path(__file__).resolve()
    roots: list[Path] = []
    for env_name in ("TRUSTWORTHY_PIPELINE_ROOT", "PIPELINE_ROOT"):
        value = os.environ.get(env_name)
        if value:
            roots.append(Path(value).expanduser().resolve())
    roots.append(Path.cwd().resolve())
    roots.extend(here.parents)
    home = Path.home()
    for skill in (
        home / ".codex" / "skills" / "research-dashboard",
        home / ".claude" / "skills" / "research-dashboard",
    ):
        if skill.exists():
            resolved = skill.resolve()
            if len(resolved.parents) >= 2:
                roots.append(resolved.parents[1])
    return roots


def _load_scope_ssot():
    for root in _candidate_roots():
        if (root / "lib" / "scope_ssot" / "__init__.py").exists():
            sys.path.insert(0, str(root))
            from lib import scope_ssot  # noqa: WPS433
            return scope_ssot
    raise ModuleNotFoundError("could not locate Trustworthy Research Pipeline lib/scope_ssot")


scope_ssot = _load_scope_ssot()


def render_js() -> str:
    data = json.dumps(scope_ssot.scope_schema(), ensure_ascii=False, sort_keys=True, indent=2)
    return (
        '"use strict";\n'
        "// Generated from lib.scope_ssot.scope_schema(); do not hand-edit field rules here.\n"
        "(function (root) {\n"
        "  root.SCOPE_SCHEMA = "
        + data.replace("\n", "\n  ")
        + ";\n"
        "})(typeof window !== \"undefined\" ? window : globalThis);\n"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="skills/research-dashboard/assets/dashboard/data/scope-schema.js")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_js(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
