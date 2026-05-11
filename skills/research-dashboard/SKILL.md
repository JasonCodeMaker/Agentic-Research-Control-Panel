---
name: research-dashboard
description: "Set up, repair, or validate the global research_html/ HTML dashboard scaffold for any research project. Use this skill whenever the user types /research-dashboard, asks to create or initialize a research dashboard, repair a broken research_html/ scaffold, install the four lane pages (brainstorm / in-progress / success / fail) before creating research packages, bring a project under the binding HTML rules R1-R17 and Trustworthy Research rules T1-T24, or set up the global research-system protocol for autonomous research agents. Project-agnostic: works in any repository the user opens. The dashboard chrome is overview-only — claims, evidence, and stage transitions live on package pages, not on the dashboard."
argument-hint: "[<root path, defaults to ./research_html>]"
allowed-tools: Bash(*), Read, Edit, Write, Glob, Grep
---

# Research Dashboard

## Purpose

Create or repair the shared `research_html/` dashboard at the working-directory root before any package work begins. The dashboard is the global research-system contract: package lanes, universal rules, optional project profile, tag-role mapping, and package inventory. It is overview-only — claims and evidence live on package surfaces.

This skill is project-agnostic. The dashboard contract is identical for every project; project specifics belong in `data/research-packages.js` (`window.RESEARCH_PROJECT_PROFILE` plus the package inventory).

## Authority

Authority order, highest first:
1. The user's invocation arguments (e.g. `/research-dashboard ./my_research_html`).
2. Form rules `R1–R17` in `<root>/rules/html-rules.html`.
3. Trustworthy Research rules `T1–T24` in `<root>/rules/trustworthy-research-rules.html`.
4. The contract documented in `references/dashboard-contract.md` (this skill).

This skill installs the rule files into `<root>/rules/` so any project gets them. Do not modify the rule files inside the user's project; if they need to change, update the skill's `assets/` instead.

## Output classification

Every text output this skill emits — intermediate progress lines, the final report, and HTML page content — classifies content by audience:

- **Both audiences** (default): facts, decisions, status, paths, and the concrete fields a human reader needs. Render inline.
- **Human-important only**: prose addressed to the user (questions, recommendations, summaries). Render inline.
- **Agent-important only**: continuity context, internal reasoning, file-map notes, "remember for next turn" pointers that the next agent benefits from but the user does not need on first read. Render collapsed by default:
  - **Chat output** (Claude Code UI): wrap the block in a markdown `>` blockquote; the UI collapses it by default.
  - **HTML pages** (dashboard chrome and lane pages): wrap the block in `<details data-audience="agent"><summary>agent context</summary>…</details>`; the `<details>` element renders closed by default so the human reader sees only the summary.

Both-audience content is written once, inline, without the blockquote or `<details>` wrapper. Do not use the blockquote form for emphasis or aesthetics — it carries audience meaning under this rule. The `data-audience="agent"` attribute and the `^> ` line prefix are stable anchors agents can grep for to recover their private notes.

## Workflow

1. **Resolve the dashboard root.** Default to `<cwd>/research_html`. If the user passes a path argument, honor it. Use absolute paths internally; do not assume the cwd matches the user's intent without confirming when ambiguous.

2. **Detect existing dashboard.** Check whether the root already exists. If it does, treat user edits as authoritative — do not overwrite without `--force`. Required files are listed in [references/dashboard-contract.md](references/dashboard-contract.md).

3. **Run the bundled script.** The scaffold script lives at `~/.claude/skills/research-dashboard/scripts/ensure_dashboard.py`. It writes a minimal compliant scaffold (idempotent: existing files are preserved) plus copies the binding rule files from this skill's `assets/` into `<root>/rules/`. Invoke it as:

   ```bash
   python ~/.claude/skills/research-dashboard/scripts/ensure_dashboard.py --root <root>
   ```

   Pass `--force` only when the user explicitly asks to overwrite.

4. **Validate.** After scaffolding, run:

   ```bash
   node --check <root>/assets/research.js
   node --check <root>/data/research-packages.js
   ```

   Then grep for the eight required `data-section` anchors and the two rule-file links in `<root>/index.html`:

   ```bash
   grep -E 'data-section="(snapshot|lanes|packages|protocol|profile|rules)"' <root>/index.html
   grep -E 'rules/html-rules.html|rules/trustworthy-research-rules.html' <root>/index.html
   ```

5. **Keep the dashboard project-agnostic.** Project objective, success rule, and cautions belong in `window.RESEARCH_PROJECT_PROFILE` inside `<root>/data/research-packages.js`. Do not edit the universal protocol cards in the same file; those are shared chrome.

6. **Report back.** State the resolved root, files written (or "preserved, no changes"), and the next suggested step (typically `/research-package` to create the first package). Apply the [Output classification](#output-classification) rule on the report itself.

## Scope (what this skill does NOT do)

- Does not create research packages — use `/research-package` for that.
- Does not edit per-package content — package surfaces own claims and evidence.
- Does not change the universal protocol or rule files in user projects — the rule files are bundled with this skill and copied as-is.

## Bundled resources

- `scripts/ensure_dashboard.py` — idempotent scaffold for the dashboard chrome plus rule-file copy.
- `references/dashboard-contract.md` — required dashboard sections, anchors, and rule citations.
- `assets/html-rules.html`, `assets/trustworthy-research-rules.html` — the binding rule files copied into every project's `<root>/rules/` so package surfaces can link them with no further setup.
