---
name: research-brainstorm
description: "The Step-3 direction-formation on-ramp. Use when the user has only a vague or partial research idea and cannot yet state a clear Direction, or types /research-brainstorm, or asks to brainstorm / shape / explore a research direction before committing. Captures cheap pre-package, pre-SSOT ideas onto the dashboard brainstorm lane, automatically generates an English brainstorm HTML detail page for each idea, and converts one or more ideas into a single Direction proposal submitted through Triage. The agent only PROPOSES the Direction — the PM ratifies. Project-agnostic. Requires a committed Project node (run /research-onboard or /research-scope first)."
argument-hint: "[<dashboard root, defaults to ./research_html>]"
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob, Agent
disable-model-invocation: false
---

# research-brainstorm (Step 3 · direction formation)

A **brainstorm** is a cheap, pre-package, pre-SSOT **idea** that lives on the dashboard brainstorm lane.
Ideas are many; commitment is the deliberate step. This skill helps a user who only has a vague idea
shape it — following the brainstorming method, grounding factual uncertainties, and sharpening
hypotheses — until one or more ideas can be **converted** into a single ratified Direction.

The trust line is unchanged: ideas are not gated (they carry no claims, metrics, or evidence). They touch
the SSOT only at **conversion**, where the synthesized Direction is *proposed* through Triage and the PM
disposes. The agent never commits the SSOT.

## Resources

**Pipeline root:** `/home/uqzzha35/Project/Trustworthy-Research-Pipeline/Trustworthy-Research-Pipeline`

| Resource | Path |
|---|---|
| Brainstorm CLI | `<pipeline-root>/skills/research-brainstorm/scripts/brainstorm.py` |
| Idea store (dashboard lane source) | `research_html/data/brainstorms.js` |
| Idea detail pages (user-readable) | `research_html/brainstorm/<YYYY-MM-DD>-<idea-id>.html` |
| Scope SSOT lib | `<pipeline-root>/lib/scope_ssot/__init__.py` |
| Triage CLI | `<pipeline-root>/skills/research-scope/scripts/triage.py` |
| Transition log | `outputs/_scope/transitions.jsonl` |
| Triage queue | `outputs/_scope/triage.jsonl` |

Brainstorm CLI commands:

```bash
python3 skills/research-brainstorm/scripts/brainstorm.py add --root research_html --title '<t>' --idea '<text>' [--rough-metric '<m>'] [--lit-refs '<json list>'] [--page-language en]
python3 skills/research-brainstorm/scripts/brainstorm.py list --root research_html
python3 skills/research-brainstorm/scripts/brainstorm.py remove --root research_html --id <idea-id>
python3 skills/research-brainstorm/scripts/brainstorm.py check-project --transitions outputs/_scope/transitions.jsonl
python3 skills/research-brainstorm/scripts/brainstorm.py direction-ready --yardstick '<json>'
python3 skills/research-brainstorm/scripts/brainstorm.py build-proposal --node-id direction/<slug> --parent-project-id <project-id> --yardstick '<json>' --provenance '<text>' --source-brainstorms '<json list of idea ids>'
```

## Precondition

A committed Project node must exist (Step 2 done):

```bash
python3 skills/research-brainstorm/scripts/brainstorm.py check-project --transitions outputs/_scope/transitions.jsonl
```

If `active_project_ids` is empty, stop and point the user at `/research-onboard` (or `/research-scope`)
to ratify a Project first. A Direction is always a child of a ratified Project.

## Procedure

**1. Shape the idea (follow the brainstorming method).**

The user usually has only a vague or partial idea. Do **not** demand a full yardstick up front. Following
the brainstorming method: ask one question at a time, surface 2-3 candidate framings with trade-offs, and
converge. Capture each distinct candidate as a cheap idea — there can be several:

```bash
python3 skills/research-brainstorm/scripts/brainstorm.py add --root research_html \
  --title 'Mixup augmentation' --idea 'Augment CIFAR-10 with mixup to lift top-1' --rough-metric 'top-1 accuracy'
```

`add` writes two user-facing surfaces in the same operation:

1. `research_html/data/brainstorms.js` gets a brainstorm-lane card.
2. `research_html/brainstorm/<YYYY-MM-DD>-<idea-id>.html` is generated and the card receives `detailPath`.

The generated HTML page is **English by default**. Keep any agent-added page content in English unless the
user explicitly requests another page language. For a one-sentence hunch, the generated page shell is
enough; for substantive brainstorming or analysis, immediately enrich that HTML page with the readable
summary, candidate framings, trade-offs, rough metric, evidence links, and next decision. Do not leave the
user with only a `brainstorms.js` row when the skill is invoked.

**2. Ground factual uncertainties.**

Whenever a framing turns on a *factual* unknown — is this novel? what is the SOTA baseline? what is the
standard metric? has this been tried? — fetch and read sources before turning the claim into shared
context. Fold the grounding back into the idea (e.g., record the real baseline in `--rough-metric`, add
`--lit-refs`). Do not assert a baseline or prior-art claim without a source or package fact.

**3. Sharpen hypotheses.**

Expand and sharpen candidate hypotheses for the most promising framing. At formation there is no scoped
direction yet, so write the sharpened ideas back as brainstorms, not as package rows.

**4. Converge and check readiness.**

Decide, with the user, which one or more ideas become **one** Direction. Synthesize a single typed
yardstick `{hypothesis, metric, baselines, success_predicate}` from them and check it is conversion-ready:

```bash
python3 skills/research-brainstorm/scripts/brainstorm.py direction-ready --yardstick '{"hypothesis":"...","metric":"...","baselines":["..."],"success_predicate":"..."}'
```

`ready=false` means a field is missing or empty — keep shaping. A baseline must be concrete (ideally
grounded by step 2), not a placeholder.

**4b. Rank candidate ideas with a separate sub-agent before forming the Direction.**

When more than one pre-package idea is in contention for a single Direction, do not pick by the
generating context's own taste. A **separate** sub-agent ranks them (`generate ≠ judge`), then the
user ratifies the winner (proposer ≠ disposer preserved — the sub-agent *ranks*, the human *ratifies*).

```python
import sys
sys.path.insert(0, "<pipeline-root>/lib")
import ranking
```

1. Write the candidate ideas to `outputs/_brainstorm/<slug>/candidates.json`.
2. `req = ranking.rank_request(idea_ids, ["outputs/_brainstorm/<slug>/candidates.json"],
   "Rank these directions best-first for a publishable research program; the answer should matter
   either way.", top_k=1)`. Dispatch a fresh ranking sub-agent (Agent tool) with `req` (paths only).
3. `parsed = ranking.parse_ranking(reply, idea_ids)`;
   `reason = ranking.assess_ranking(parsed["ranking"], idea_ids,
   producer="brainstorm-ideas", judge="brainstorm-ranker")`. If `reason`, stop and surface it.
4. `winner = ranking.select_top_k(parsed["ranking"], 1)[0]`. Persist
   `ranking.write_ranking_verdict("outputs/_brainstorm/<slug>/verdicts/",
   {"producer": "brainstorm-ideas", "judge": "brainstorm-ranker", "scope_version": <v>,
   "candidate_set_id": "_brainstorm/<slug>/candidates.json", "candidate_set": idea_ids,
   "ranking": parsed["ranking"], "selected": [winner], "rationale": parsed["rationale"]})`.
5. Present `winner` + `parsed["rationale"][winner]` to the user for ratification. Record the rationale
   + `ranking_id` as conversion provenance in the new package's `brainstorm.html`.

If only one idea is in contention, this step is skipped — proceed directly to step 5.

**5. Build the Direction proposal and submit it through Triage.**

```bash
P=$(python3 skills/research-brainstorm/scripts/brainstorm.py build-proposal \
  --node-id direction/<slug> --parent-project-id <project-id> \
  --yardstick '<json>' --provenance 'brainstorms:<idea-ids>' --source-brainstorms '<json list of idea ids>')
python3 skills/research-scope/scripts/triage.py propose --log outputs/_scope/triage.jsonl --item "$P"
python3 skills/research-scope/scripts/triage.py pending --log outputs/_scope/triage.jsonl
```

`build-proposal` validates the yardstick against the SSOT schema (reject-before-propose) and carries
`source_brainstorms` so the consumed ideas are known at conversion. Show the pending item and **STOP** —
ratifying the Direction is the PM's decision.

## Hand-off (PM action, then the existing chain)

This mirrors `research-scope`'s human-accept path:

1. PM `triage.py dispose --decision accept`, then commits with `research-op --op scope-transition`
   (`gate=USER_CROSS_MODEL_AUDIT`). The Direction enters the SSOT.
2. The existing chain takes over: `plan_milestones.py` proposes milestones; after they are committed,
   `create_from_scope.py` materializes the package. Pass the consumed idea ids so they are frozen into the
   package's `brainstorm.html` provenance sub-page and removed from the brainstorm lane:

   ```bash
   python3 skills/research-package/scripts/create_from_scope.py \
     --direction-id <direction-id> --root research_html \
     --transitions outputs/_scope/transitions.jsonl \
     --source-brainstorms '<json list of idea ids>'
   ```

## Scope (what this skill does NOT do)

- Does not commit the SSOT — it only proposes a pending Direction Triage item.
- Does not create packages or milestones — those are the existing `create_from_scope.py` / `plan_milestones.py`.
- Ideas are not research-op surfaces — `add`/`remove` write `brainstorms.js` directly; they carry no gates.

## Output contract

| Path | Written by | Contents |
|---|---|---|
| `research_html/data/brainstorms.js` | this skill (`add`/`remove`) | pre-package ideas rendered on the brainstorm lane, each with `detailPath` |
| `research_html/brainstorm/<YYYY-MM-DD>-<idea-id>.html` | this skill (`add`, then optional Edit) | English-by-default, user-readable brainstorm page for the idea |
| `outputs/_scope/triage.jsonl` | `triage.py propose` | one pending Direction item (carries `source_brainstorms`) |
| `outputs/_scope/transitions.jsonl` | PM only (via research-op) | committed Direction — never this skill |

## Done condition

The shaped idea(s) are on the brainstorm lane, each has a readable HTML page linked by `detailPath`, and —
when the user is ready — a conversion-ready Direction is a pending Triage item carrying its
`source_brainstorms`, shown to the user. The Direction is not yet in effect; it takes effect only after PM
acceptance and the `research-op --op scope-transition` commit.
