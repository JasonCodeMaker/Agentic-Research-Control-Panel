# Exp-live Page Contract

`research_html/live.html` is a global read-only dashboard page. It is scaffolded by `/research-dashboard`.

Data flow:

1. Fetch `../outputs/_live/runs.jsonl`.
2. Fold launch and terminal records in the browser.
3. Fetch each run's `status.json`.
4. Join package metadata from `data/research-packages.js`.
5. Render measured state, progress, latest metrics, gate text, last-output age, resource sample, and evidence links.

Trust boundaries:

- The page renders readings, not verdicts.
- The page does not write package surfaces or runtime artifacts.
- `eta` is copied literally from `status.json`.
- STALE and RUN_FAILED runs appear in the attention rail.
- Empty, fetch-failed, and parse-failed states must be explicit and visible.
