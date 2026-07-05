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
5. Render measured state, the launched config (the run's command, the open-run disambiguator), progress, latest metrics, bounded health (state + at most one truncated reason), last-output age, resource sample, and evidence links. The verdict-flavored gate is not rendered here — it lives on tracker/results.

Trust boundaries:

- The page renders readings, not verdicts.
- The page does not write package surfaces or runtime artifacts.
- `eta` is copied literally from `status.json`.
- STALE and RUN_FAILED runs appear in the attention rail as compact cards. A failure clears from the rail and the alarm counts when it is either relaunched with `--retry-of <run_id>` (superseded) or listed in `outputs/_live/acknowledged.json` (a JSON array of `run_id`s, or `{"run_ids": [...]}`, fetched read-only). Either way the run stays in the terminal history, annotated. This is data-driven, not a page write.
- Empty, fetch-failed, and parse-failed states must be explicit and visible.
- The API server is an observation/data-plane boundary. Its failure is
  `repair_required` dashboard debt, not experiment completion or launch truth.
