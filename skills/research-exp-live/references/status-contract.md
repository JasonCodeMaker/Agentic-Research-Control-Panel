# Exp-live status contract

`status.json` is the atomic, run-local status snapshot for one authorized Run:

```text
$RESEARCH_ROOT/experiments/<package>/<experiment>/<run>/status.json
```

It is runtime evidence, not a global index. Management-open Run discovery comes from the Run aggregate
in `$RESEARCH_ROOT/state/events.jsonl`. `lib.experiments.reconcile` repairs a missing launch or
terminal callback from valid Run files.

## Fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Status schema version. |
| `run_id` | Run identity. |
| `package_id` | Owning Package. |
| `experiment_id` | Canonical accepted Scope Experiment identity. |
| `experiment_local_id` | Directory-safe Experiment id used in the Run path. |
| `status` | `QUEUED`, `RUNNING`, `STALE`, `COMPLETED`, `FAILED`, `HALTED`, or `SKIPPED`. |
| `health` | `{state: OK|WARN|ERROR, reasons: []}`. |
| `progress` | Known step, total, percent, epoch, or phase fields. |
| `latest_metrics` | Most recent parsed metric values. |
| `source_map` | Metric name to telemetry source. |
| `throughput` | Measured rate, unit, and `stable_since`, or `null`. |
| `first_output_at`, `last_output_at`, `started_at` | Epoch seconds, or `null`. |
| `heartbeat_timeout` | Silence threshold used to derive `STALE`. |
| `anomalies`, `log_lines` | Monitoring counters. |
| `resource` | Optional GPU sample. |
| `pid`, `harvester_pid` | Child and harvester process ids. |
| `exit_code`, `ended_at` | Terminal evidence, otherwise `null`. |
| `launch_failed` | True when the command did not start. |
| `callback_errors` | Bounded errors from management callbacks. |

The harvester writes this file atomically and refreshes it on its watchdog clock. Readers may derive
`STALE` again from `last_output_at` and `heartbeat_timeout` if the harvester has died.

`status.json` does not authorize a Run. `run.json`, `context.json`, and the management
`RunLaunchAuthorized` event provide that authorization.

## Observation mapping

| Live-check field | Source |
| --- | --- |
| Run state | `status` |
| Last output | `last_output_at` |
| Progress | `progress` |
| Latest metrics | `latest_metrics` |
| Resource use | `resource`, otherwise `unmeasured` |
| Health | `health` |

The agent supplies the live action and next-check time. Write those decisions through `research-op`;
do not add them to `status.json`.

## Terminal rule

A Run is mechanically terminal only when `status` is `COMPLETED`, `FAILED`, `HALTED`, or `SKIPPED`.
The snapshot must also contain `exit_code` and `ended_at`. Scientific claims still require
`result.json` and valid EvidenceRefs.

The interface under `$RESEARCH_ROOT/interface/` is a read-only projection of these facts. It never
replaces either management state or Run evidence.
