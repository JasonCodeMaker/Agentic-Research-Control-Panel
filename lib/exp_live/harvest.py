#!/usr/bin/env python3
"""Deprecated import path for the canonical run harvester.

All writes are delegated to :mod:`lib.experiments.harvest`, whose write scope
is one ``.research/experiments/<package>/<experiment>/<run>`` directory.
"""

from lib.experiments.harvest import (  # noqa: F401
    HarvestResult,
    RunState,
    main,
    run_command,
)
from lib.experiments.parsing import compile_custom_regex, gpu_sampler, parse_line

__all__ = [
    "HarvestResult",
    "RunState",
    "compile_custom_regex",
    "gpu_sampler",
    "main",
    "parse_line",
    "run_command",
]


if __name__ == "__main__":
    raise SystemExit(main())
