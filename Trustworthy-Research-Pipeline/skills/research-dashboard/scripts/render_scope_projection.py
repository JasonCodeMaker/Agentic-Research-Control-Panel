"""Render and check the read-only dashboard scope projection.

The canonical store is var/research/_scope/transitions.jsonl; the projection at
research_html/data/scope-projection.json is fold(transitions) — derived, never a second source of
truth. `render` is the only writer; `check` rejects any projection that drifts from the fold.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import scope_ssot  # noqa: E402


def render(transitions_path, projection_path):
    """Write the projection = fold(transitions). Returns the projection."""
    proj = scope_ssot.fold(scope_ssot.read_log(transitions_path))
    projection_path = Path(projection_path)
    projection_path.parent.mkdir(parents=True, exist_ok=True)
    projection_path.write_text(json.dumps(proj, indent=2, sort_keys=True, ensure_ascii=False),
                               encoding="utf-8")
    return proj


def check(transitions_path, projection_path):
    """Raise RuleViolation if the on-disk projection does not equal fold(transitions)."""
    proj = json.loads(Path(projection_path).read_text(encoding="utf-8"))
    scope_ssot.assert_consistent(proj, scope_ssot.read_log(transitions_path))


def main(argv=None):
    p = argparse.ArgumentParser(description="render/check the dashboard scope projection")
    p.add_argument("cmd", choices=["render", "check"])
    p.add_argument("--transitions", required=True)
    p.add_argument("--projection", required=True)
    args = p.parse_args(argv)
    if args.cmd == "render":
        render(args.transitions, args.projection)
        print(f"rendered projection -> {args.projection}")
    else:
        check(args.transitions, args.projection)
        print("projection consistent with transitions")


if __name__ == "__main__":
    main()
