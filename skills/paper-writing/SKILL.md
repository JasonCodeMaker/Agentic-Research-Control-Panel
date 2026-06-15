---
name: paper-writing
description: "Standalone research-paper production component. Use whenever the user wants to write, draft, revise, audit, compress, polish, clean up AI-sounding or overclaiming prose, fit a page limit, or run pre-submission checks on a paper — abstracts, introductions, methods, experiments, related work, conclusions, .tex/.md manuscripts, conference/journal submissions — or to build a project/venue writing adapter from a reference corpus. Targets ML/Deep-Learning papers by default (method, system-for-ML, benchmark, empirical, theory, safety/eval, interdisciplinary), but works for any research paper. The skill is named paper-writing; all runtime artifacts live under ./paper/. Does NOT require Trustworthy-Research-Pipeline. (For replying to peer reviews use the rebuttal skill instead.)"
---

# Paper Writing Component

A four-layer paper-production system. The **agent writes prose**; **deterministic scripts gate it**.
That split is the trust guarantee: facts are preserved and claims are evidence-checked by code, not by
the model's good intentions.

## When this skill triggers, do this first

1. Identify the `paper_id` (ask if unknown). Its home is `./paper/projects/<paper_id>/`.
2. If the project does not exist, run mode **init**.
3. Read the project's `context/paper_context.md` if present — it is **P0, binding**.
4. If present, read `context/paper_plan.md` before `context/global_structure.md`; the plan sets section order and claim assignment, while the global structure is a human-agent narrative skeleton derived from that plan.
5. Translate the user's request into exactly one mode below, then act.

Run the CLI from the user's project root so it creates/uses `./paper/` there:

```bash
python3.13 scripts/paper_writing.py <mode> <paper_id> [options]
```

(Each backing script is also runnable directly and importable for tests.)

### Typical first run

`init` only scaffolds the tree and a `paper.yaml` stub. **You must fill `paper.yaml`** — title, venue,
the contribution claims, and the evidence each claim points to — *from the user's notes/results/manuscript*
before `context`. `context` then validates that evidence and refuses to mark unsupported claims as
`supported`; it never invents the missing facts.

```
init → (fill paper.yaml) → context → plan → [global structure] → [convert-corpus → adapter → confirm] → draft/revise → audit → presubmit
```

The bracketed corpus/adapter steps are optional: without a reference corpus the adapter falls back to the
active profile, so drafting works immediately.

## The four layers and their priority

| P | Layer | Lives in | Rule |
| --- | --- | --- | --- |
| P0 | Hard Preserve | `./paper/projects/<id>/context/` | Never change facts, citations, equations, labels, metric/dataset names, numeric results, or locked claims. |
| P1 | Workflow Kernel | `references/workflow_kernel/` | The lifecycle decides which action is legal next. |
| P2 | Project/Venue Adapter | `./paper/projects/<id>/adapter/dynamic_paper_adapter.md` | Venue style overrides generic templates. Never beats P0/P1. |
| P3 | Global Guide Bank | `references/global_guide_bank/` | Section templates fill gaps P2 leaves open. |
| P4 | Cleanup | `scripts/section_audit.py` | Strip AI-taste, overclaims, empty transitions. |

**P2 beats P3.** Never copy or paraphrase corpus prose — corpus teaches structure only.

## Modes → scripts

| Mode | Script | What it does |
| --- | --- | --- |
| `init <id>` | `common.init_project` | Create the project directory tree + `paper.yaml` stub. |
| `context <id>` | `build_paper_context.py` | Assemble `paper_context.md` + `claim_evidence_map.md` + `figure_table_inventory.md` from local inputs; emit a gap report. |
| `convert-corpus <id>` | `convert_corpus.py` + `evaluate_conversion.py` | Convert `inputs/corpus_raw/` to Markdown/JSON when supported (Docling/manual), run the readability gate, write manifests + reports. |
| `adapter <id>` | `adapter_inputs.py` → `generate_adapter.py` → `validate_adapter.py` | Build style cards → style profile → `dynamic_paper_adapter.md`; **stop at the human gate**. |
| `plan <id>` | `workflow_kernel.py` | Emit `context/paper_plan.md` (section order + per-section claim assignment) from context + active profile. |
| `draft <id> --section S` | `section_audit.py` + `validate_claims.py` + `validate_adapter.py` | You draft section S; scripts require any generated adapter to be confirmed, load only the S guide, audit it, and block unsupported/overclaimed content. |
| `revise <id> --section S --file F` | `validate_claims.py` + `section_audit.py` + `validate_adapter.py` | Revise F; preserve P0; apply confirmed adapter rules; record a revision-log entry. |
| `audit <id> --file F` | `section_audit.py` + `validate_adapter.py` | Style/cleanup audit of one file with confirmed adapter rules when available. |
| `export <id> --format markdown\|latex` | `paper_writing.py` | Concatenate section drafts (kernel order) into Markdown or a compilable LaTeX scaffold. |
| `presubmit <id> --pdf P [--tex … --log … --anonymous]` | `presubmission_check.py` | Mechanical LaTeX/PDF checks (pages, refs, fonts, figures, anonymization, common log/source issues). Report only. |

`draft`/`revise` are gates, not generators: **you** write the prose, then these modes require any
generated adapter to be confirmed, load only the current section guide, apply confirmed adapter rules,
audit style, and block any unsupported claim or P0 fact mutation. Fix the draft on failure — never edit
the gate.

## The workflow kernel (P1)

Lifecycle stages (in order): **context → plan → section drafts → integration → compression → presubmission**.
Default section order (introduction-twice rule):

```
Draft-0 Introduction → Evaluation/Results → Method/Design → Background (if needed)
→ Related Work → Final Introduction → Abstract → Conclusion
```

The kernel is **domain-neutral**. All venue conventions live in `references/workflow_kernel/profiles/`.
Default profile when none is selected: `ml_dl_general.md`. Systems/networking conventions live ONLY in
`systems_networking.md` — never assume a systems venue.

After `plan`, maintain any human-agent writing skeleton as `context/global_structure.md`. This file is not
a new gate or source of facts: it translates `context/paper_plan.md` into a readable paper-level narrative
for section drafting. It must be created after the plan and must defer to `paper.yaml`,
`context/paper_context.md`, and `context/claim_evidence_map.md` on factual boundaries.

## Hard rules (never violate)

1. **Never add facts** — no new results, citations, numbers, or claims during writing.
2. **Never change P0 content** — equations, citation keys, labels, notation, metric/dataset names,
   numeric values are preserved verbatim.
3. **Never copy corpus prose** — style cards describe structure and rhetoric only.
4. **Adapter is human-gated** — no manuscript revision begins until `dynamic_paper_adapter.md` is confirmed.
5. **Load only the current section guide** — do not load the whole guide bank.
6. **Claim-evidence is a hard gate** — every Abstract/Introduction claim needs a `supported` evidence row.

## How the agent and scripts divide work

- The **agent** fills `paper.yaml` from notes/manuscript (judgment), writes section prose, and enriches
  adapter descriptions.
- The **scripts** assemble the typed contracts, run the readability/claim/style/pre-submission gates,
  and refuse to let unsupported or fact-mutating content pass. On a gate failure, fix the draft — do
  not edit the gate.

See [`README.md`](README.md) for the directory layout and [`references/ATTRIBUTION.md`](references/ATTRIBUTION.md)
for source attribution.
