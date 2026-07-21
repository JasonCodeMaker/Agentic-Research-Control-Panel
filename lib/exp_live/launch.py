#!/usr/bin/env python3
"""Deprecated import path for the canonical experiment launcher.

The compatibility surface preserves the module name only.  It has no legacy
storage mode and cannot write an ``outputs`` tree.
"""

from lib.experiments.launch import (  # noqa: F401
    LaunchResult,
    PreparedRun,
    freeze_context,
    launch_run,
    main,
    prepare_run,
)

__all__ = [
    "LaunchResult",
    "PreparedRun",
    "freeze_context",
    "launch_run",
    "main",
    "prepare_run",
]


if __name__ == "__main__":
    raise SystemExit(main())
