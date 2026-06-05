"""Render and check the read-only dashboard scope projection.

The canonical store is outputs/_scope/transitions.jsonl; the projection at
research_html/data/scope-projection.json is fold(transitions) — derived, never a second source of
truth. `render` is the only writer; `check` rejects any projection that drifts from the fold.
"""

import argparse
import json
import sys
from pathlib import Path


def _load_scope_ssot():
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "lib",                          # skill source tree
        here.parents[2] / "lib",                          # project with lib/ at root
        here.parents[2] / "Trustworthy-Research-Pipeline" / "lib",  # repo embedding this package
    ]
    for lib in candidates:
        if lib.exists():
            sys.path.insert(0, str(lib))
            try:
                import scope_ssot  # noqa: WPS433
                return scope_ssot
            except ImportError:
                continue
    return None


scope_ssot = _load_scope_ssot()


class RuleViolation(Exception):
    pass


def _read_log(log_path):
    path = Path(log_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _fold(records):
    projection = {}
    for rec in records:
        node = rec.get("node")
        if node:
            projection[rec["node_id"]] = node
    return projection


def _assert_consistent(projection, records):
    expected = _fold(records)
    if projection != expected:
        raise RuleViolation("scope projection drift: does not match fold(transitions)")


def read_log(log_path):
    return scope_ssot.read_log(log_path) if scope_ssot else _read_log(log_path)


def fold(records):
    return scope_ssot.fold(records) if scope_ssot else _fold(records)


def assert_consistent(projection, records):
    if scope_ssot:
        scope_ssot.assert_consistent(projection, records)
    else:
        _assert_consistent(projection, records)


def _write_projection_js(json_path, projection):
    js_path = Path(json_path).with_suffix(".js")
    payload = json.dumps(projection, indent=2, sort_keys=True, ensure_ascii=False)
    js_path.write_text("window.RESEARCH_SCOPE_PROJECTION = " + payload + ";\n", encoding="utf-8")


def render(transitions_path, projection_path):
    """Write the projection = fold(transitions). Returns the projection."""
    proj = fold(read_log(transitions_path))
    projection_path = Path(projection_path)
    projection_path.parent.mkdir(parents=True, exist_ok=True)
    projection_path.write_text(json.dumps(proj, indent=2, sort_keys=True, ensure_ascii=False),
                               encoding="utf-8")
    if projection_path.suffix == ".json":
        _write_projection_js(projection_path, proj)
    return proj


def check(transitions_path, projection_path):
    """Raise RuleViolation if the on-disk projection does not equal fold(transitions)."""
    proj = json.loads(Path(projection_path).read_text(encoding="utf-8"))
    assert_consistent(proj, read_log(transitions_path))


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
