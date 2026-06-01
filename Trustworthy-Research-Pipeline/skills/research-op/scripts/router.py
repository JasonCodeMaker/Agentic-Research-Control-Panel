"""Dispatch (op, target) to the matching handler in ops/.

Imports are deferred to dispatch time so this module loads even when some
ops handlers don't yet exist (Phase 3 builds them one task at a time).
Each op handler module (check.py, insert.py, update.py, delete.py) must
provide a handle() function with the signature:
  handle(pkg: str, target: str|None, payload: dict, state: dict) -> tuple[str, list[str]]
returning (validation_status, files_touched).
"""


def dispatch(op: str, pkg: str, target: str | None, payload: dict, state: dict) -> tuple[str, list[str]]:
    """Run the handler; return (validation_status, files_touched).

    Args:
        op: operation name (check, insert, update, delete)
        pkg: package id
        target: target name (None for check)
        payload: operation payload dict
        state: current (category, status) state dict

    Returns:
        (validation_status, files_touched) tuple where validation_status is
        a string like "passed" or "failed" and files_touched is a list of
        file paths modified by the operation.

    Raises:
        ValueError: if op is unknown
        ImportError: if the corresponding ops module doesn't exist yet
    """
    if op == "check":
        from ops import check as _check
        return _check.handle(pkg, target, payload, state)
    if op == "insert":
        from ops import insert as _insert
        return _insert.handle(pkg, target, payload, state)
    if op == "update":
        from ops import update as _update
        return _update.handle(pkg, target, payload, state)
    if op == "delete":
        from ops import delete as _delete
        return _delete.handle(pkg, target, payload, state)
    raise ValueError(f"unknown op: {op}")
