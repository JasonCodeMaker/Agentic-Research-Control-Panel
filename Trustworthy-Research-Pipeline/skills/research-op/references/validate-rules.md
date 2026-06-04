# Pattern B — write-time validate rules

Every Insert / Update / Delete in `research-op` runs the rules below before any
byte hits disk. Rule ids are the values that appear in the rejection envelope's
`rule` field.

## Per-target rules

### Insert: methodsTried row (I2)
- `methodstried-six-fields`: payload must have exactly `{method, hypothesis, gate, measured, verdict, evidencePath}`. Extra or missing keys reject.
- `methodstried-verdict-enum`: `verdict ∈ {pass, fail, inconclusive}`.
- `methodstried-evidence-resolves`: `evidencePath` is either a real file under `outputs/<pkg>/` or `output/`, or an HTML anchor `results.html#<exp-anchor>` that exists on disk.
<!-- planned, not yet implemented: methodstried-source-row-exists — the upstream results.html row at evidencePath exists with a verdict already finalized -->

### Insert: results.html result-gate row (I6)
- `result-gate-ten-cols`: all 10 columns from WORKFLOW.md required schema are present.
- `result-gate-validity-enum`: `Validity ∈ {ok, partial, fail, unmeasured}`.
- `result-gate-pass-triple-check` *(planned, not yet implemented)* (only if `verdict=pass`): the P5 triple-check passes — hypothesis string-eq frozen contract; metric/dataset/protocol/dedup/cutoff string-eq frozen contract; evidence file's manifest names the canonical eval split.

### Insert: results.html result block (I7)
- `result-block-six-parts`: HTML must contain the 6 anchors — `data-block="title"`, `data-block="summary"` (text ≤ 25 words), `data-block="detail"` (in `<details>` closed), `data-block="main-table"`, `data-block="insight"`, `data-block="ablation"` (or explicit `<!-- no ablation -->` comment).
- `result-block-details-closed`: every `<details>` in the block lacks `open` attr (R-no-details-open).

### Update: results.html verdict cell (U10)
- `verdict-mechanical`: the verdict string MUST equal `predicate(measured)` where `predicate` is the frozen success.predicate from plan.html. Refuse if they differ. The actual measured value is read from `evidencePath`.

### Update: status — lane-crossing (U1)
- `lane-t1-ack-present`: the payload must include a non-empty `ack_token` field for any lane-crossing status update (the T1 acknowledgement value).
- `lane-required-fields`: every required field for the destination cell (per `schema.js`) must be present in the inventory entry.
- `lane-edge-legal`: the `(old-category, old-status) -> (new-category, new-status)` edge is a legal cell in the 18-cell state machine (the `STATES` table in `scripts/transitions.py`, documented in [matrix.md](matrix.md) §4.5); terminal-frozen cells (`(success, ADOPTED)`, `(fail, ARCHIVED)`) are never a legal destination.

### Update: status — acquit into the success lane (U1, success-bound)
These fire in addition to the lane-crossing rules above whenever the destination category is `success`.
- `acquit-needs-verdict`: the payload must carry a non-empty `verdict` record (judge, verdict, evidence) for any acquit into the success lane.
- `acquit-judge-independent`: the verdict's judge must satisfy the independence constraint for the task's `autonomy_level` (default `"supervised"`); at `"autonomous"` the judge must be cross-family from the producer. Implemented via `lib/verifier.assess_acquit(verdict, level)` — acquit only on a `sound` verdict.

### Insert: doc-file (I9) + paired doc-card
- `doc-file-path-under-package`: file path matches `research_html/packages/<pkg>/docs/<slug>.html`.
- `doc-card-six-parts`: paired card has the 6-part shape (title, tldr, tags, preview, link, last-updated) and 5 `data-doc-*` attrs from the companion HTML-design spec.
- `doc-group-rationale-present`: parent section in `docs/index.html` carries `data-doc-group-rationale`.

### Insert: tracker-live-check-row (I3)
- `live-check-twelve-cols`: all 12 columns from WORKFLOW.md required schema are present.
- `live-check-time-local`: `Time` field is local wall-clock (no `Z`, no `+00:00` offset).

### Delete: methodsTried row (D4)
- `methodstried-terminal-frozen`: refuse if `(category, status)` is in `(success/*, fail/*)`.

### Delete: experiments-row (D1)
- `experiments-pre-launch-only`: refuse if any `experiments[].status` for the package is one of `running`, `completed`, `failed`.

## Universal rules (every op)

- `payload-json-valid`: `--payload` parses as JSON (this fires before the per-target rules above).
- `target-known`: `--target` is a value in `transitions.TARGETS` (this fires before the legality lookup).
