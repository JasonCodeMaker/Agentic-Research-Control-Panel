# Exp-live telemetry sources

Telemetry enriches a Run but does not control its lifecycle. With no metric adapter match, the
harvester still records process status, output heartbeat, exit code, and Run evidence.

Adapter order:

1. cooperating JSON lines;
2. custom regular expressions with named groups;
3. tqdm-style progress;
4. generic `name=value` or `name: value` metrics;
5. phase markers;
6. anomaly markers.

`status.json.source_map` records the source selected for each metric. A later value may replace an
earlier value, but the reader can still see which adapter produced it.

W&B and TensorBoard identifiers belong in `run.json.telemetry`. Their services are optional.
`status.json` remains the routine live observation, and `$RESEARCH_ROOT/state/` remains the
management authority.

GPU samples are also observations. When `--gpu-sample` is disabled or unavailable, `resource` is
`null`; no reader may infer idle or busy capacity from that absence. Resource availability snapshots
belong to the XDG runtime cache described by `research-resource`, not to the Run's management state.
