"""Option-B inventory bridge: project the SSOT scope tree into the dashboard inventory.

The Project node becomes the profile; each Direction/Task becomes a card whose status tracks the
SSOT. The inventory is a read-only projection of fold(transitions) — `assert_inventory_consistent`
rejects any hand-edited inventory that diverges from the canonical scope.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import scope_ssot  # noqa: E402


def build_inventory(projection):
    """Map the folded scope tree to {profile, cards} — profile from the Project node, one card per Direction/Task."""
    profile, cards = {}, []
    for node_id, node in projection.items():
        if node["level"] == "project":
            y = node["yardstick"]
            profile = {"north_star": y.get("north_star"),
                       "contribution_spine": y.get("contribution_spine"),
                       "non_goals": y.get("non_goals"), "version": node["version"]}
        else:
            cards.append({"id": node_id, "level": node["level"], "status": node["status"],
                          "version": node["version"], "hypothesis": node["yardstick"].get("hypothesis")})
    cards.sort(key=lambda c: c["id"])
    return {"profile": profile, "cards": cards}


def assert_inventory_consistent(inventory, projection):
    """Raise RuleViolation if the inventory does not equal the projection-derived inventory."""
    if inventory != build_inventory(projection):
        raise scope_ssot.RuleViolation("inventory drift: does not match the SSOT projection")


def render(transitions_path, inventory_path):
    """Write the inventory projection derived from the transition log. Returns the inventory."""
    inv = build_inventory(scope_ssot.fold(scope_ssot.read_log(transitions_path)))
    inventory_path = Path(inventory_path)
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(json.dumps(inv, indent=2, sort_keys=True, ensure_ascii=False),
                              encoding="utf-8")
    return inv


def check(transitions_path, inventory_path):
    """Raise RuleViolation if the on-disk inventory drifts from the SSOT projection."""
    inv = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    assert_inventory_consistent(inv, scope_ssot.fold(scope_ssot.read_log(transitions_path)))


def main(argv=None):
    p = argparse.ArgumentParser(description="render/check the dashboard SSOT inventory projection")
    p.add_argument("cmd", choices=["render", "check"])
    p.add_argument("--transitions", required=True)
    p.add_argument("--inventory", required=True)
    args = p.parse_args(argv)
    if args.cmd == "render":
        render(args.transitions, args.inventory)
        print(f"rendered inventory -> {args.inventory}")
    else:
        check(args.transitions, args.inventory)
        print("inventory consistent with transitions")


if __name__ == "__main__":
    main()
