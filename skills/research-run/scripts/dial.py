"""Dial auto-revert: a direction/project scope transition reverts affected Tasks to Supervised and
locks them until the agent re-grounds. Task-level transitions do not revert. The affected set is the
transition's dial_revert list (computed by scope_ssot propagation).
"""


def revert_on_scope_change(tasks, transition):
    """Return tasks with any affected Task reverted to Supervised + locked (direction/project only)."""
    if transition.get("level") not in ("direction", "project"):
        return tasks
    affected = set(transition.get("dial_revert", []))
    return [
        {**t, "control_mode": "SUPERVISED", "locked": True} if t["id"] in affected else t
        for t in tasks
    ]
