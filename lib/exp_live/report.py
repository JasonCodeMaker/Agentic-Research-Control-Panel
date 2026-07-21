#!/usr/bin/env python3
"""Deprecated import path for canonical run reporting.

The former live-index reader is intentionally absent.  Open-run discovery now
comes only from the management-state projection.
"""

from lib.experiments.report import main, open_runs, run_summary

__all__ = ["main", "open_runs", "run_summary"]


if __name__ == "__main__":
    raise SystemExit(main())
