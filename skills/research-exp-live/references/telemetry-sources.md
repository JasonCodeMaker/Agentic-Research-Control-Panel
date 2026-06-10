# Exp-live Telemetry Sources

Lifecycle and provenance do not depend on telemetry richness. With zero adapter matches, the harness still records liveness, output heartbeat, status, exit code, log path, and global index entries.

Adapter order:

1. cooperating JSON lines;
2. explicit custom regex named groups;
3. tqdm-style progress bars;
4. generic `name=value` or `name: value` metrics;
5. phase markers;
6. anomaly markers.

Metric source precedence is visible through `status.json.source_map`; values are not silently overwritten without their source being recorded.

External telemetry such as W&B or TensorBoard is optional. External IDs can be stored in `meta.json.telemetry`, but `status.json` remains the workflow source of truth for routine live checks and `live.html`.
