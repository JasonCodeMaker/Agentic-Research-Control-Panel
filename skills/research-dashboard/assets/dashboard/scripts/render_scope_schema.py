#!/usr/bin/env python3
"""Render the browser Scope schema from lib.scope_ssot."""

import argparse
import json
from pathlib import Path

from lib import scope_ssot


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
