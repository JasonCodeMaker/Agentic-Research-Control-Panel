# Exp-live Status Contract

`status.json` is the routine live-check source of truth for wrapper-launched runs. It is written with a temp file and atomic rename.

Required top-level fields:

| Field | Meaning |
| --- | --- |
| `run_id`, `pkg`, `exp_id` | Run identity and task-spine join keys. |
| `status` | One of `QUEUED`, `RUNNING`, `COMPLETED`, `RUN_FAILED`, `RUN_HALTED`, `STALE`, `SKIPPED`. |
| `health` | `{state: OK|WARN|ERROR, reasons: []}`. |
| `progress` | Step, total, percent, epoch, or phase when known. |
| `latest_metrics` | Latest metric values parsed from telemetry. |
| `source_map` | Metric key to telemetry source. |
| `throughput` | Rate, unit, and `stable_since` when known. |
| `eta` | Literal `unknown` until 30 minutes of stable measured throughput clears. |
| `first_output_at`, `last_output_at`, `started_at` | Epoch seconds. |
| `heartbeat_timeout` | Seconds of silence before STALE; lets any reader re-derive STALE from `last_output_at` age when the harvester itself died. |
| `anomalies`, `log_lines` | Bounded monitoring counters. |
| `resource` | GPU sample (`--gpu-sample`, refreshed on watchdog ticks) or `null`. |
| `pid`, `harvester_pid` | Child and harvester process ids for mechanical liveness checks. |
| `exit_code`, `ended_at` | Terminal evidence; `null` while open. |

Freshness: the harvester re-writes `status.json` on a watchdog clock (independent of output), so STALE and silence-WARN appear on disk during quiet periods. Writes are throttled during chatty output (at most ~1/s, forced on first output, anomalies, and terminal).

Live-check row mapping:

| Live-check column | Source |
| --- | --- |
| `Run State` | `status` |
| `Last Log Time` | `last_output_at` |
| `Progress` | `progress` |
| `Latest Metrics` | `latest_metrics` |
| `Resource Use` | `resource` or `unmeasured` |
| `ETA` | `eta` |

The agent still owns `Agent`, `Live Action`, `Next Check`, and `Artifact Status`.

Fact-backed package ownership:

- `status.json` is the live-run source of truth and may be refreshed by the
  harvester/watchdog.
- `outputs/_live/dashboard_server.json` is dashboard-server health/provenance
  only. It may contain `repair_required`, but it never replaces `status.json`
  or blocks experiment launch/completion truth.
- `research_html/data/packages/<pkg>/tables/live_checks.csv` stores extracted
  live-check snapshots for `tracker.html`.
- `research_html/data/packages/<pkg>/tables/resource_allocation.csv` stores the
  tracker resource-allocation projection rows.
- The tracker CSV rows are package-surface facts. They do not replace
  `status.json` as raw runtime truth.
- Completed result claims and methods `PASS` rows must be backed by extracted
  result facts, not manual tracker rows.
