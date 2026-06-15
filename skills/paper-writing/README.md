# paper-writing User Guide

This guide is for users working with Codex, Claude Code, or another coding agent. You do not need to think in terms of Python scripts. The normal interface is conversation:

1. You provide project facts, evidence, notes, drafts, and goals.
2. You ask the agent to use `paper-writing`.
3. The agent creates and updates `./paper/projects/<paper_id>/`.
4. The agent reports outputs, blockers, and the next recommended step.

The skill name is `paper-writing`. Runtime artifacts live under the current project:

```text
./paper/projects/<paper_id>/
```

## What This Skill Does

Use `paper-writing` to move a research project from evidence and notes to a paper draft with gates:

- create a paper workspace;
- extract and lock paper facts;
- map claims to local evidence;
- create a paper plan;
- optionally learn project/venue style from a reference corpus;
- draft or revise sections;
- audit claims, numbers, citations, labels, and style;
- integrate and compress the paper;
- export Markdown/LaTeX scaffold;
- run pre-submission checks.

The skill does not invent missing results, citations, baselines, datasets, or claims. If evidence is missing, it should say so.

## What You Provide

The better your inputs, the better the paper workflow. You can give the agent any subset of:

| Input | Example | Why It Matters |
| --- | --- | --- |
| Paper id | `grdr-iclr2027` | Stable project handle under `./paper/projects/`. |
| Target venue | `ICLR`, `NeurIPS`, `TMLR`, `CVPR` | Chooses default style profile and adapter target. |
| Paper type | method, benchmark, system-for-ML, empirical, theory, safety/eval | Shapes section plan and claim style. |
| Result evidence | tables, CSVs, logs, metric summaries | Claims must point to these files. |
| Method notes | design docs, equations, diagrams, implementation notes | Source for method section. |
| Existing drafts | intro/method/eval fragments | Can be audited or revised instead of generated from scratch. |
| Reference corpus | accepted papers, journal examples, PDFs or Markdown | Optional source for project/venue adapter. |
| Constraints | page limit, anonymity, deadline, format | Used during compression/export/presubmit. |

You do not need to put everything in the perfect folder first. You can tell the agent where files are, and ask it to organize them under `./paper/`.

## Full Workflow: User-Agent Protocol

Each stage below explains what you should say, what the agent should produce, and what the next step is.

### Stage 1: Start The Paper Project

Goal: create the paper workspace and choose a stable paper id.

Prompt:

```text
Use paper-writing to start a paper project named grdr-iclr2027.
The target venue is ICLR.
This is a method paper.
Put all paper-writing artifacts under ./paper/.
```

What the agent should do:

- create `./paper/projects/grdr-iclr2027/`;
- create the standard paper workspace;
- create a starter `paper.yaml`;
- ask for missing facts instead of filling them with guesses.

What you should receive:

- the created project path;
- a short explanation of what still needs to be provided;
- the next prompt to lock facts.

Next prompt:

```text
Now build the paper facts from my notes and results. Do not invent unsupported claims.
```

### Stage 2: Lock The Paper Facts

Goal: turn messy research materials into a local paper source of truth.

Prompt:

```text
Use paper-writing to build the paper context for grdr-iclr2027.
My results are in outputs/main_results.md.
My method notes are in notes/method.md.
My dataset and baseline notes are in notes/eval_setup.md.
Extract the paper identity, claims, evidence map, limitations, figures, and terminology.
Do not invent claims. Mark unsupported claims as missing or partial.
```

What the agent should do:

- read the files you named;
- fill or update `paper.yaml`;
- map every claim to an evidence file;
- preserve exact metric names, numbers, dataset names, citation keys, and LaTeX labels;
- generate the context artifacts.

What you should receive:

- `paper_context.md`;
- `claim_evidence_map.md`;
- `figure_table_inventory.md`;
- `gap_report.md`;
- a short list of supported, partial, missing, or overclaim risks.

Next prompt if context is incomplete:

```text
The missing evidence list is correct. Help me weaken unsupported claims and update the paper context.
```

Next prompt if context is ready:

```text
Use the locked paper context to create the paper plan.
```

### Stage 3: Plan The Paper Narrative

Goal: decide what the paper says, in what order, and where each claim belongs.

Prompt:

```text
Use paper-writing to create a paper plan for grdr-iclr2027.
Base it only on the locked paper context.
Assign each main claim to the right section.
Use the generalized ML/DL workflow, not a systems-specific workflow unless the evidence requires it.
```

What the agent should do:

- read `paper_context.md` and `claim_evidence_map.md`;
- create `context/paper_plan.md`;
- use the introduction-twice workflow;
- assign evidence-bearing claims to evaluation, final introduction, and abstract;
- identify required figures/tables;
- create or update `context/global_structure.md` only after the plan when the project needs a human-agent paper-level writing skeleton.

What you should receive:

- section order;
- per-section purpose;
- claim-to-section mapping;
- missing figure/table checklist;
- optional global structure skeleton for reader journey and section roles;
- recommendation for whether to use a venue adapter.

Next prompt:

```text
Decide whether this paper needs a venue adapter. I can provide reference papers if useful.
```

### Stage 4: Decide Whether To Use A Venue Adapter

Goal: decide whether generic ML/DL writing guidance is enough, or whether this project needs target-venue style adaptation.

Prompt without corpus:

```text
Use paper-writing to decide whether grdr-iclr2027 needs a project/venue adapter for ICLR.
I do not have a clean reference corpus yet.
Tell me whether the default ML/DL profile is enough.
```

Prompt with corpus:

```text
Use paper-writing to prepare an ICLR adapter for grdr-iclr2027.
Reference papers are in paper/projects/grdr-iclr2027/inputs/corpus_raw/.
Convert them if needed, exclude failed conversions, and generate a reviewable adapter.
Stop before using the adapter.
```

What the agent should do:

- explain whether an adapter is useful;
- convert PDFs/docs to AI-readable Markdown when needed;
- reject failed or partial conversions for adapter extraction;
- extract style cards and a style profile;
- generate `dynamic_paper_adapter.md`;
- stop for human review.

What you should receive:

- conversion/readability summary if corpus was used;
- style profile summary;
- generated adapter path;
- explicit request for approval.

Next prompt if adapter is good:

```text
The adapter is acceptable. Confirm it and use it for future draft, revise, and audit steps.
```

Next prompt if adapter is wrong:

```text
The adapter is too aggressive about contribution format. Revise it to keep prose contributions, then ask me to confirm again.
```

### Stage 5: Draft The First Sections

Goal: create section drafts while keeping claims grounded.

Recommended order:

```text
Draft-0 Introduction -> Evaluation/Results -> Method/Design -> Background if needed -> Related Work -> Final Introduction -> Abstract -> Conclusion
```

Prompt for Draft-0 Introduction:

```text
Use paper-writing to draft the Draft-0 Introduction for grdr-iclr2027.
Use only supported or explicitly bounded claims from claim_evidence_map.md.
Do not add new numbers, citations, datasets, or baselines.
If a claim is missing evidence, either omit it or phrase it as a limitation.
After drafting, run the paper-writing gate and tell me whether it is ready.
```

Prompt for Evaluation:

```text
Use paper-writing to draft the Evaluation section.
Ground each result claim in the evidence files.
Preserve metric names and values exactly.
Make clear which baselines, datasets, and ablations are present or missing.
Run the draft gate afterward.
```

Prompt for Method:

```text
Use paper-writing to draft the Method section from the locked method notes.
Preserve notation and module names.
Do not introduce unimplemented components.
Run the section audit afterward.
```

What the agent should do:

- draft the requested section;
- load only the current section guide;
- apply the confirmed adapter if one exists;
- run claim/style/fact gates;
- report blockers rather than silently weakening checks.

What you should receive:

- draft file path under `drafts/`;
- readiness result;
- list of unsupported claims, changed facts, style issues, or adapter violations;
- recommended fix.

Next prompt when blocked:

```text
Fix the draft according to the gate report. Do not edit the gate. If evidence is missing, weaken the claim.
```

Next prompt when ready:

```text
Proceed to the next section in the paper-writing order.
```

### Stage 6: Revise Existing Drafts

Goal: improve sections that already exist without changing locked facts.

Prompt:

```text
Use paper-writing to revise drafts/final_introduction.md for grdr-iclr2027.
Preserve all P0 facts: numbers, citation keys, LaTeX labels, equations, metric names, dataset names, and claim meaning.
Apply the confirmed adapter.
Report every change category and run the gate after revision.
```

What the agent should do:

- read the draft;
- compare it against the locked context;
- remove unsupported overclaims;
- improve paragraph flow;
- preserve all locked facts;
- run the gate.

What you should receive:

- revised draft;
- readiness result;
- summary of what changed;
- remaining blockers if any.

Next prompt:

```text
If the section is ready, integrate it with the other sections and check for duplicated claims.
```

### Stage 7: Integrate The Paper

Goal: make the paper coherent across sections.

Prompt:

```text
Use paper-writing to integrate the current grdr-iclr2027 sections.
Check for repeated claims, inconsistent terminology, missing transitions, missing figures, and unsupported cross-section claims.
Preserve all locked facts.
```

What the agent should do:

- align terminology;
- ensure the same claim is not over-repeated;
- move claims to the right sections;
- check figure/table references;
- re-run audits for changed sections.

What you should receive:

- integration summary;
- list of edited sections;
- remaining consistency issues;
- next compression or export recommendation.

Next prompt:

```text
Compress and polish the integrated draft for the target page limit.
```

### Stage 8: Compress And Polish

Goal: reduce length and remove weak prose without changing facts.

Prompt:

```text
Use paper-writing to compress grdr-iclr2027 for a 9-page anonymous ICLR submission.
Remove repetition and AI-sounding phrasing.
Do not change equations, numbers, citation keys, labels, dataset names, metric names, or claim meaning.
Run gates after compression.
```

What the agent should do:

- compress repeated motivation;
- remove generic adjectives and empty transitions;
- preserve limitations;
- preserve all locked facts;
- re-run gates.

What you should receive:

- compressed sections;
- before/after summary;
- gate result;
- remaining page-limit risks.

Next prompt:

```text
Export the current paper as Markdown and a LaTeX scaffold.
```

### Stage 9: Export The Manuscript

Goal: produce files you can inspect, compile, or move into a venue template.

Prompt:

```text
Use paper-writing to export grdr-iclr2027 as Markdown and LaTeX.
Tell me where the files are and whether the LaTeX is a scaffold or venue-ready.
```

What the agent should do:

- collect section drafts in workflow order;
- produce Markdown export;
- produce LaTeX scaffold export;
- explain limitations of the scaffold.

What you should receive:

- path to Markdown export;
- path to LaTeX scaffold;
- note that official venue template integration may still be needed.

Next prompt:

```text
Run pre-submission checks on the exported LaTeX/PDF artifacts.
```

### Stage 10: Pre-Submission Check

Goal: catch mechanical problems before submission.

Prompt:

```text
Use paper-writing to run pre-submission checks for grdr-iclr2027.
This is an anonymous 9-page submission.
Check the LaTeX source, compile log, and PDF if available.
Report page count, undefined refs/cites, missing figures, duplicate labels, font issues, anonymity leaks, and TODO markers.
```

What the agent should do:

- inspect available `.tex`, `.log`, and `.pdf` files;
- report mechanical problems;
- avoid editing source unless you explicitly ask for fixes;
- write a presubmission report.

What you should receive:

- `logs/presubmission_check.md`;
- list of blocking issues;
- list of safe fix suggestions;
- final recommendation.

Next prompt:

```text
Fix the blocking presubmission issues one by one, preserving P0 facts.
```

## Common Conversation Shortcuts

Use these prompts when you know what you want but not which internal mode is needed.

### Start From Existing Results

```text
Use paper-writing for paper_id grdr-iclr2027.
My results are in results/main_table.md, method notes are in notes/method.md, and evaluation setup is in notes/eval_setup.md.
Build the paper context, identify supported and missing claims, then propose the next step.
```

Expected result:

- paper workspace is created if needed;
- claims are mapped to evidence;
- missing facts are explicit;
- agent recommends plan or evidence cleanup.

### Turn A Draft Into A Safer Paper Section

```text
Use paper-writing to audit and revise drafts/final_introduction.md.
Preserve all locked facts.
Tell me every unsupported claim, changed number, citation/label issue, and adapter violation before finalizing edits.
```

Expected result:

- revised section or blocker report;
- exact list of factual risks;
- readiness status.

### Ask For Venue Adaptation

```text
Use paper-writing to adapt this paper for ICLR.
I have reference papers in corpus_raw.
Generate a project/venue adapter from structure only, do not copy prose, and stop for my review.
```

Expected result:

- corpus conversion summary;
- style cards/profile;
- reviewable adapter;
- no manuscript edits until you approve.

### Ask For Compression

```text
Use paper-writing to compress the current draft for a 9-page limit.
Remove repetition and generic phrasing.
Do not change numbers, citations, labels, equations, datasets, metrics, or claim meaning.
```

Expected result:

- shorter draft;
- preservation summary;
- gate result;
- remaining length risks.

### Ask For Submission Readiness

```text
Use paper-writing to check whether this paper is submission-ready.
This is anonymous and has a 9-page limit.
Inspect available Markdown, LaTeX, log, and PDF artifacts, then report blockers.
```

Expected result:

- presubmission report;
- page/font/ref/citation/figure/anonymity/TODO issues;
- next fix recommendation.

## How To Interpret Agent Outputs

| Agent Output | Meaning | What You Should Do |
| --- | --- | --- |
| `supported` | Claim evidence exists and declared value is found. | Safe to use with bounded wording. |
| `partial` | Evidence exists, but the declared value or full support is missing. | Weaken claim or add evidence. |
| `missing` | Evidence file is absent. | Add evidence or remove the claim. |
| `overclaim` | Claim exceeds available evidence. | Rewrite claim before drafting. |
| `ready=True` | Current gate passed. | Move to next section/stage. |
| `ready=False` | A gate failed. | Fix draft/evidence/adapter; do not weaken the gate. |
| `adapter_blocked=True` | Adapter exists but is not confirmed. | Review and approve/revise adapter. |

## Correct Usage Rules

- Ask the agent to use `paper-writing` explicitly when you want this workflow.
- Give the agent evidence locations and constraints; do not ask it to infer results from memory.
- Treat `./paper/projects/<paper_id>/context/` as binding after context is built.
- Do not ask the agent to invent missing claims, citations, baselines, or numbers.
- Do not use raw PDF corpus directly for style adaptation; ask the agent to convert and gate it first.
- Do not proceed with drafting against an unconfirmed adapter.
- Do not treat a failed gate as a nuisance. It is the mechanism that protects the paper from unsupported writing.
- Use official venue templates after LaTeX scaffold export when the target venue requires a specific format.

## Artifact Map

| Artifact | Purpose |
| --- | --- |
| `paper.yaml` | User/project facts, claims, evidence pointers, terminology. |
| `context/paper_context.md` | Locked paper context used by the agent. |
| `context/claim_evidence_map.md` | Claim support status and allowed wording. |
| `context/gap_report.md` | Missing venue/baseline/result/evidence issues. |
| `context/paper_plan.md` | Section order and claim assignment. |
| `context/global_structure.md` | Human-agent paper-level skeleton derived after the plan; narrative only, not a fact source. |
| `adapter/dynamic_paper_adapter.md` | Project/venue writing rules. |
| `adapter/adapter_review.md` | Human gate status for adapter use. |
| `inputs/corpus_conversion/readability_report.md` | Whether corpus conversion is usable. |
| `drafts/*.md` | Section drafts. |
| `exports/markdown/` | Combined Markdown manuscript. |
| `exports/latex/` | LaTeX scaffold. |
| `logs/presubmission_check.md` | Submission-readiness report. |

## What The Agent Should Never Do

- It should never silently add new experimental results.
- It should never change metric values to make prose smoother.
- It should never add citation keys that are not in the project terminology/evidence.
- It should never copy prose from reference corpus papers.
- It should never use a generated adapter before human confirmation.
- It should never claim a paper is ready when `claim_evidence_map.md` has unresolved core claims.

## Attribution

Adapted from three MIT-licensed source projects. See [`references/ATTRIBUTION.md`](references/ATTRIBUTION.md).
