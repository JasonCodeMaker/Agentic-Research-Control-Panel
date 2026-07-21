# Exp-live page contract

`$RESEARCH_ROOT/interface/live.html` is a generated, read-only view. A missing page does not block
launch, monitoring, reconciliation, or completion.

## Data flow

When the interface server is running, the page prefers:

```text
GET /api/live/runs?include_status=1
GET /api/live/status/<run-id>
GET /api/live/log/<run-id>
```

The server reads Run aggregates from `$RESEARCH_ROOT/state/` and resolves each Run directory below
`$RESEARCH_ROOT/experiments/`. It rejects runtime paths outside that tree.

If the API is unavailable, the page may read `data/live-runs.jsonl` and
`data/live-acknowledged.json` from the generated interface. These files are short-lived projections
created during an interface rebuild. They can be stale and must not authorize a workflow decision.

## Trust boundary

- The page displays observations. It does not write state or Run files.
- The page never renders a scientific verdict from a live metric.
- Runtime status comes from `status.json`; Run identity and lifecycle come from management state.
- Failed or stale fetches are visible rather than converted into empty success states.
- Attention acknowledgment and retry relationships originate in state. Their interface JSON files
  are projections.
- All API endpoints are read-only.

The server's static document root is `$RESEARCH_ROOT/interface/`. Its process metadata and log live
under `$XDG_RUNTIME_DIR/trustworthy-research/<workspace-hash>/`, or the per-user temporary fallback
selected by `ResearchPaths`. Server failure creates interface debt only.
