# Composite events — surface fan-out map

Each event below triggers ≥ 1 Insert and ≥ 1 Update across multiple surfaces in
the same atomic transaction. The agent invokes `--event <name>` once; research-op
fans out, runs Pattern B on each surface in the fan-out, and either succeeds for
every surface or aborts entirely.

The authoritative fan-out for each event is the `EVENTS` table in
[`../scripts/events.py`](../scripts/events.py); this file is the human-readable map. Where the two
differ, `events.py` is what actually runs — keep them in sync.

## CHAIN_DONE

Trigger: a chain log file ends with `=== … done ===`.
Fan-out (auto, package-wide — `events.py` `CHAIN_DONE`):
1. `update status` to NEXT_ACTION_READY
2. `update openRuns` to "none"
3. `update lastAction` to "chain done"
4. `update last-updated-time` on tracker.html, results.html

The per-phase ops — `update results-block` / `results-verdict` / `experiments-status` to `completed`,
and `update tracker-chosen-route` — are **caller-invoked once per closed phase** (with the phase id in
the payload), not auto-fanned in v1; see the note in `events.py`.

## CHECKPOINT_SAVED

Trigger: `output/<exp>/best_model.pt` written.
Fan-out:
1. `update tracker-live-check-row` for the exp (state=COMPLETED)
2. `update tracker-resource-allocation-row` for the exp (Status=COMPLETED)
3. `insert results-gate-row` for the exp (if not present)
4. `update results-verdict` (Pattern B verdict-mechanical fires)
5. `update experiments-status` to "COMPLETED"
6. `update last-updated-time` on tracker.html, results.html

## SENTINEL_WRITE

Trigger: `manifests/*.txt` written.
Fan-out: **deferred** — registered in `events.py` with an empty fan-out until the surface map is
enumerated from a real running package (Phase-6 pilot). Invoking `--event SENTINEL_WRITE` is a no-op
transaction today; until then propagate the sentinel via explicit `--op update` calls.

## PHASE_MARKER

Trigger: `--- P` or `### P` appears in chain log.
Fan-out: **deferred** (empty fan-out in `events.py`); same status as SENTINEL_WRITE.

## CANDIDATE_SUBMITTED

Trigger: `candidates/<label>/<dataset>/*.json` written.
Fan-out: **deferred** (empty fan-out in `events.py`); same status as SENTINEL_WRITE.
