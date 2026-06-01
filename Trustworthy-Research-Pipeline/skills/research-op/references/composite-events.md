# Composite events — surface fan-out map

Each event below triggers ≥ 1 Insert and ≥ 1 Update across multiple surfaces in
the same atomic transaction. The agent invokes `--event <name>` once; research-op
fans out, runs Pattern B on each surface in the fan-out, and either succeeds for
every surface or aborts entirely.

## chain-done

Trigger: a chain log file ends with `=== … done ===`.
Fan-out:
1. `update results-block` for every phase the chain closed (compute summary)
2. `update results-verdict` for each closed phase
3. `update tracker-chosen-route` (set the route from chain summary)
4. `update status` to NEXT_ACTION_READY
5. `update openRuns` to "none"
6. `update lastAction` to "chain done"
7. `update last-updated-time` on tracker.html, results.html
8. `update experiments-status` to "completed" for each closed phase

## checkpoint-saved

Trigger: `output/<exp>/best_model.pt` written.
Fan-out:
1. `update tracker-live-check-row` for the exp (state=completed)
2. `update tracker-resource-allocation-row` for the exp (Status=completed)
3. `insert results-gate-row` for the exp (if not present)
4. `update results-verdict` (Pattern B verdict-mechanical fires)
5. `update experiments-status` to "completed"
6. `update last-updated-time` on tracker.html, results.html

## sentinel-write

Trigger: `manifests/*.txt` written.
Fan-out: see spec § 4 + WORKFLOW.md Fact Propagation Contract table.

## phase-marker

Trigger: `--- P` or `### P` appears in chain log.
Fan-out: see spec.

## candidate-json

Trigger: `candidates/<label>/<dataset>/*.json` written.
Fan-out: see spec.
