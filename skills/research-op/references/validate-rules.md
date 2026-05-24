# Pattern B — write-time validate rules

Every Insert / Update / Delete in `research-op` runs the rules below before any
byte hits disk. Rule ids are the values that appear in the rejection envelope's
`rule` field.

## Per-target rules

### Insert: methodsTried row (I2)
- `methodstried-six-fields`: payload must have exactly `{method, hypothesis, gate, measured, verdict, evidencePath}`. Extra or missing keys reject.
- `methodstried-verdict-enum`: `verdict ∈ {pass, fail, inconclusive}`.
- `methodstried-evidence-resolves`: `evidencePath` is either a real file under `var/research/<pkg>/` or `output/`, or an HTML anchor `results.html#<exp-anchor>` that exists on disk.
- `methodstried-source-row-exists`: the upstream `results.html` row at `evidencePath` exists with a verdict already finalized.

### Insert: results.html result-gate row (I6)
- `result-gate-ten-cols`: all 10 columns from WORKFLOW.md required schema are present.
- `result-gate-validity-enum`: `Validity ∈ {ok, partial, fail, unmeasured}`.
- `result-gate-pass-triple-check` (only if `verdict=pass`): the P5 triple-check passes — hypothesis string-eq frozen contract; metric/dataset/protocol/dedup/cutoff string-eq frozen contract; evidence file's manifest names the canonical eval split.

### Insert: results.html result block (I7)
- `result-block-six-parts`: HTML must contain the 6 anchors — `data-block="title"`, `data-block="summary"` (text ≤ 25 words), `data-block="detail"` (in `<details>` closed), `data-block="main-table"`, `data-block="insight"`, `data-block="ablation"` (or explicit `<!-- no ablation -->` comment).
- `result-block-details-closed`: every `<details>` in the block lacks `open` attr (R-no-details-open).

### Update: results.html verdict cell (U10)
- `verdict-mechanical`: the verdict string MUST equal `predicate(measured)` where `predicate` is the frozen success.predicate from plan.html. Refuse if they differ. The actual measured value is read from `evidencePath`.

### Update: status — lane-crossing (U1)
- `lane-t1-ack-present`: the destination cell's `data-ack-value=""` slot for `lane-transition` must be non-empty in the package HTML before this Update can write.
- `lane-required-fields`: every required field for the destination cell (per `schema.js`) must be present in the inventory entry.
- `lane-edge-legal`: the `(old-category, old-status) -> (new-category, new-status)` edge exists in `references/state-machine.md`.

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

### Insert: brainstorm-section (I10)
- `brainstorm-category-only`: refuse if `category != "brainstorm"`.

## Universal rules (every op)

- `payload-json-valid`: `--payload` parses as JSON (this fires before the per-target rules above).
- `target-known`: `--target` is a value in `transitions.TARGETS` (this fires before the legality lookup).
