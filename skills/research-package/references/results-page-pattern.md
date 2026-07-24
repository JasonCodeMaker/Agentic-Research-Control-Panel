# Result table contract

`results.html` is a read-only projection of predefined Experiment tables. Its
only job is to show the measurements the user needs to judge each Experiment.
It contains no Hypothesis restatement, evaluation-contract banner, or
package-level result-gate ledger.

## Truth chain

```text
Experiment.resultSchema
  -> frozen Run context and schema SHA-256
  -> comprehensive evaluation CSV
  -> deterministic per-table CSVs and manifest
  -> finalized result.json with hash-bound EvidenceRefs
  -> results.html
```

State owns the schema. The Run directory owns measurements and evidence. HTML
owns nothing.

## Design the schema before execution

For each Experiment, decide what comparison the user must make after the Run:

1. Select only the metrics needed to judge that Experiment.
2. Fix every model, method, seed, dataset slice, and comparison arm as rows.
3. Use one or more `main` tables for primary evidence.
4. Add an `ablation` table only for an actual component or policy ablation.
5. Omit `resultSchema` when the Experiment needs no human result table.

A non-empty schema uses version 1:

```json
{
  "version": 1,
  "tables": [
    {
      "id": "effectiveness",
      "type": "main",
      "title": "Retrieval effectiveness",
      "rowLabel": "Method",
      "rows": [
        {
          "id": "sqr",
          "label": "SQR",
          "selector": {"method": "sqr", "seed": "42"}
        }
      ],
      "columns": [
        {
          "id": "r1",
          "label": "R@1",
          "metric": "recall_at_1",
          "unit": "percent",
          "nullable": false
        }
      ]
    }
  ]
}
```

Table, row, and column ids are stable lowercase identifiers. Row selectors are
unique scalar maps. Columns name the exact source metric and unit; set
`nullable: true` only when the metric can be legitimately undefined.
The schema contains no measured value, verdict, prose summary, or evidence
path.

After Package activation and before the first Run, write the schema through
`research-op`:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> --pkg <package-id> \
  --op update --target experiment-result-schema \
  --payload '<schema-binding-json>' \
  --idempotency-key <stable-key> \
  --expected-version <package-version>
```

The payload contains exactly `scope_experiment_id` and the complete validated
`resultSchema` object shown above.

Re-query between Package mutations. The gateway permits this operation only in
an unblocked `ACTIVE / CONTEXT_LOADED` Package and rejects it after the
Experiment has any Run.

## Produce the comprehensive CSV

The evaluation script computes its complete metric set and writes one CSV
inside the Run evidence boundary. It may contain more rows and metrics than the
human tables need. Every row has:

```text
metric,value,unit,status,reason,<selector fields...>
```

`metric`, `unit`, and selector values must use the exact schema strings.
Allowed statuses are:

- `MEASURED`: `value` is a finite number.
- `FAILED`: `value` is empty or `null`, and `reason` is non-empty.
- `UNDEFINED`: the column is nullable, `value` is empty or `null`, and
  `reason` is non-empty.

Do not use a missing row to mean pending, failed, or undefined. Every expected
cell must match exactly one source row.

## Extract and finalize

After the Run is terminal:

```bash
python3 -m lib.experiments.result_tables \
  --workspace <workspace> \
  --research-root <research-root> \
  --run-dir <run-dir> \
  --source <comprehensive-metrics.csv>
```

The extractor reads the schema frozen in `context.json` and writes:

```text
<run-dir>/files/result-tables/
  <table-id>.csv
  manifest.json
```

It rejects a missing or duplicate source match, unit mismatch, invalid status,
illegal null, row or column drift, schema mismatch, and hash drift. The
manifest binds the Run identity, schema SHA-256, source CSV, every table CSV,
extractor identity, and EvidenceRef hashes.

Finalize with that manifest:

```bash
python3 -m lib.experiments.extract \
  --workspace <workspace> \
  --research-root <research-root> \
  --run-dir <run-dir> \
  --payload <result-payload.json> \
  --result-table-manifest <run-dir>/files/result-tables/manifest.json
```

Never hand-edit a derived table, manifest, `result.json`, or generated HTML.

## Render the interface

Render one block per Experiment and zero or more tables inside it:

- `main` tables are open by default;
- `ablation` tables are collapsed by default;
- before a matching finalized Run, preserve the full schema shape, mark the
  table `planned`, and display every null cell as `/`;
- verified tables show the Run id and source hash;
- `FAILED` and `UNDEFINED` cells display `/` with their reason available;
- schema mismatch or unverified legacy evidence stays visibly unverified and
  never fills a schema-backed table.

The renderer may select the latest finalized Run only when the schema digest
and all manifest evidence verify. It never reconstructs a missing value from
logs, prose, `metrics.jsonl`, or an older HTML page.

After state or result finalization, rebuild through `research-dashboard`.
Agents inspect state and Run evidence, never this rendered page.
