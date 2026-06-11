---
name: research-exp-live
description: "Use when launching, monitoring, resuming, or stopping long-running research experiment commands that should be tracked through structured runtime artifacts, adaptive live checks, startup health gates, or global live.html."
---

# Research Exp Live

## Purpose

Track long-running research commands through a workflow-owned run envelope, not through repeated raw scrollback reading. The local source of truth is the run directory under `outputs/<pkg>/runs/<run_id>/`; the user-facing overview is `research_html/live.html`.

This skill governs wrapper-launched runs only. Unwrapped runs stay on the default `workflow.ts`
`<=600s` live-loop deadline.

## Authority

1. User invocation and active package plan.
2. `workflow.ts` lifecycle, run status enum, live-check row, stop gate, and fact propagation.
3. This skill for exp-live launch, startup health, adaptive cadence, typed evidence, and open-runs stop checks.
4. Runtime files under `outputs/<pkg>/runs/<run_id>/`.

Scheduler-neutral / re-entry-tool-neutral: this skill states the evidence, deadlines, and decisions that must hold. Use whatever re-entry facility the environment provides, but meet the deadline recorded in `Next Check`.

## Pre-flight

- `research_html/live.html` exists. It is scaffolded by `/research-dashboard`; this skill only requires it.
- The package exists in `research_html/data/research-packages.js`.
- The target `--exp` exists in that package's `experiments[]` task spine.
- The command is a long-running experiment, training run, evaluation sweep, feature extraction, index build, preprocessing job, or print-only script. If the active plan explicitly marks it as an untracked one-shot, document that exception and use the unwrapped fallback loop.

## Launch

Use the wrapper for tracked long-running commands:

```bash
python3 lib/exp_live/launch.py \
  --pkg <package-id> \
  --exp <P1> \
  --tmux-session <name> \
  --heartbeat-timeout 600 \
  -- bash scripts/run_experiment.sh
```

Optional telemetry flags include `--metrics-regex`, `--total-steps`, `--wandb-run-id`, and `--tensorboard-logdir`. The local run directory remains canonical even when external telemetry exists.

Two more optional flags feed the adaptive protocol:

- `--expected-duration minutes|hours|days` — the coarse duration class for the cadence evidence ladder. Scheduling input only; package surfaces still record `est_time=unknown` until the 30-minute measured rule clears.
- `--gpu-sample` — sample `nvidia-smi` for the run's GPUs on each watchdog tick so the live-check `Resource Use` column fills from `status.json.resource`. Off by default; without it `resource` is `null` and the column renders `unmeasured`.

Record the allocation row exactly as the `workflow.ts` ticket requires:

- `Session/Job`: tmux session
- `Runtime Root`: `outputs/<pkg>/runs/<run_id>/`
- `Log Path`: `outputs/<pkg>/runs/<run_id>/log.txt`
- `Expected Duration`: `est_time=unknown` unless the 30-minute measured-throughput rule has already cleared

A tracked run launched outside `launch.py` is a workflow violation unless the active plan explicitly says it is untracked.

## Startup health gate

Purpose: P1 verified health. The first check is due within the startup window, default 120 seconds after launch. Widen it only for known slow starts and record why.

Read `status.json`. The gate passes only when:

- process lifecycle is still active or terminal state is mechanically recorded;
- `first_output_at` is set;
- `health.state` is `OK` or `WARN`.

Until the gate passes, do not pick up unrelated work that risks missing the deadline, and do not end the turn without a re-entry due inside the startup window.

If `health.state=ERROR`, or the run exits inside the startup window, run:

```bash
python3 lib/exp_live/report.py --run outputs/<pkg>/runs/<run_id> --tail 50
```

Then route by the `workflow.ts` ticket: repair, fix implementation, ask, or block. Launch provenance may be recorded immediately, but you must not report startup-confirmed, healthy, or running normally until this gate passes.

## Adaptive Cadence

Purpose: replace the fixed clock for wrapper-launched runs.

Evidence ladder, best first:

1. measured ETA from stabilized throughput in `status.json`;
2. harvester progress trend from `progress.pct`, `progress.step`, `progress.total`, and `throughput.rate`;
3. coarse expected-duration class from launch readiness or a launch flag;
4. unknown duration.

Interval guide:

| Remaining duration | Default next interval |
| --- | --- |
| `<= 15 min` | 2-5 min |
| `<= 1 h` | about 10 min |
| `<= 6 h` | 15-30 min |
| `> 6 h` | 30-60 min |
| unknown | 10 min until evidence improves |

Hard cap 60 min: no open wrapper run goes unchecked longer than this. Tighten freely; never loosen past the cap.

Tighten triggers:

- `health.state=WARN`
- anomaly count increases
- throughput materially drops
- remaining ETA is less than twice the current interval
- `status=STALE` or `health.state=ERROR` means act now

Scheduling estimates are not recorded ETA claims. Package surfaces still record `est_time=unknown` until the existing 30-minute measured-throughput rule clears.

## Per-check Obligations

At every wrapper-run check:

1. Read `status.json` for every open wrapper run. Do not tail `log.txt` for routine monitoring.
2. Update the live-check row from `status.json` fields verbatim:
   - `Run State` = `status`
   - `Last Log Time` = `last_output_at`
   - `Progress` = `progress`
   - `Latest Metrics` = `latest_metrics`
   - `Resource Use` = `resource` or `unmeasured`
   - `ETA` = `eta`
3. Derive and record `Next Check` from the adaptive cadence above.
4. Run `scan-events` for the package and fan out every emitted artifact event through `research-op`. Artifact propagation follows this same adaptive cadence; do not create a second fixed artifact-scan loop for wrapper-launched runs.
5. Emit one compact `perRun[].statusLine` per open run. Its `progress=`, `performance=`, and `est_time=` segments must equal the values read from `status.json`.
6. Arm re-entry at or before `Next Check`.

Ending a turn with an open wrapper run and no re-entry at or before `Next Check` is a workflow violation.

## STALE, Anomalies, and Failures

If `status.json` says `STALE`, or `health.state` degrades, check immediately. Liveness is mechanical: the tmux session named in `meta.json`, the child `pid` and `harvester_pid` recorded in `status.json`, and `last_output_at` age vs the recorded `heartbeat_timeout`. The harvester's watchdog re-writes `status.json` on its own clock, so silence flips STALE on disk even between your checks; if the harvester itself died, derive STALE from `last_output_at` age (as `report.py --open` does). Route from verified state; do not infer from a quiet terminal.

Use bounded raw-log intake only after an issue:

```bash
python3 lib/exp_live/report.py --run outputs/<pkg>/runs/<run_id> --tail 50
```

## Verified Completion

Purpose: P2 verified completion. A wrapper-launched run is finished iff `status.json` is terminal:

- `COMPLETED`
- `RUN_FAILED`
- `RUN_HALTED`

The terminal snapshot must include `exit_code` and `ended_at`. Elapsed time, quiet logs, ETA expiry, and expected artifacts are not completion evidence.

Immediately before recording completed facts, re-read `status.json`. Then proceed through the usual ticket surfaces: final live-check row, result recording through research-op, `scan-events` propagation, and bounded post-mortem on failure.

## Open-runs Stop Gate

Before `BLOCKED`, `STOPPED`, or session end:

```bash
python3 lib/exp_live/report.py --open
```

If it lists non-terminal runs, every listed run must have an armed re-entry at or before its recorded `Next Check`. Otherwise the stop is refused. After terminal lines land and `report.py --open` returns an empty list, the wrapper-run part of the stop gate is clear.

On resume, reconcile the tracker Resume Block `Open Runs` against `report.py --open` and each listed run's `status.json` before trusting tracker state.

## Worked Example

Check 1 at startup:

```text
status=RUNNING health=OK first_output_at=set progress=step 20/50000 eta=unknown
Decision: startup gate passed
Next Check: +10 min because duration is unknown and health is OK
scan-events: empty
P2: progress=step 20/50000; performance=pending(first_eval); est_time=unknown; action=CONTINUE_RUN
```

Check 2 after progress trend:

```text
status=RUNNING health=OK progress=step 1200/50000 latest_metrics=loss 0.41 eta=unknown
Decision: continue
Next Check: +15 min because long-run trend is stable but ETA is not yet claimable
scan-events: CHECKPOINT_SAVED fan-out applied if emitted
P2: progress=step 1200/50000; performance=loss=0.41; est_time=unknown; action=CONTINUE_RUN
```

Short-run contrast:

```text
status=RUNNING health=OK progress=80% eta=unknown
Decision: continue, tighten near finish
Next Check: +2 min
```

Failure path — the startup gate refusing (P1):

```text
Check 1 at +90 s:
status=RUN_FAILED health=ERROR reasons=["Traceback", "exit_code=1"] first_output_at=set
Decision: startup gate REFUSED — do not report launched/healthy/running normally
python3 lib/exp_live/report.py --run outputs/<pkg>/runs/<run_id> --tail 50
  -> tail shows ImportError in dataloader
Route: FIX_IMPLEMENTATION; record the failed run as evidence;
relaunch later with --retry-of <run_id>
```

## References

- `references/status-contract.md` - schema and live-check column mapping
- `references/telemetry-sources.md` - adapter/source precedence
- `references/live-page-contract.md` - read-only page and polling contract
