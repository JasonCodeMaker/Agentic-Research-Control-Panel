# Exp-live Page Contract

`research_html/live.html` is a global read-only dashboard page. It is scaffolded by `/research-dashboard`.

Data flow:

1. Prefer `GET /api/live/runs?include_status=1` from the local dashboard server.
2. The server reads `outputs/_live/runs.jsonl`, folds launch and terminal
   records, and attaches each eligible run's `status.json`.
3. If the API is unavailable, fall back to the legacy direct file path:
   fetch `../outputs/_live/runs.jsonl`, fold records in the browser, then fetch
   each eligible run's `status.json`.
4. Join package metadata from `data/research-packages.js`.
5. Render measured state, progress, latest metrics, gate text, last-output age, resource sample, and evidence links.

Trust boundaries:

- The page renders readings, not verdicts.
- The page does not write package surfaces or runtime artifacts.
- `eta` is copied literally from `status.json`.
- STALE and RUN_FAILED runs appear in the attention rail.
- Empty, fetch-failed, and parse-failed states must be explicit and visible.
- The API server is an observation/data-plane boundary. Its failure is
  `repair_required` dashboard debt, not experiment completion or launch truth.
