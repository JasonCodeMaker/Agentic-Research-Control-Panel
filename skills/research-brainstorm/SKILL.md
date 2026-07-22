---
name: research-brainstorm
description: "Use when the user wants to create, refine, merge, archive, or review one standalone Brainstorm before Package conversion."
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob, Agent
---

# Research brainstorm

## Objective

Turn one vague idea, including one broad research direction, into one
continuously revised, state-governed Brainstorm document. It remains outside
Package and Scope authority until the user explicitly approves conversion.

## Definition

- A Brainstorm is a standalone pre-Package aggregate with a governed document.
- It is not a Package, Direction, or Experiment and cannot authorize a Run.
- One broad research direction maps to one Brainstorm by default.
- Reproduction, task migration, causal audit, ablation, risk, and similar work
  remain Sections or Stages when they share one core research question.
- Refine the same Brainstorm in place. Do not create a sibling record for each
  iteration, concern, or stage.
- Convert only after the document is stable, the user has audited it, and the
  user explicitly approves the exact Brainstorm revision.
- Keep the body free-form. Do not turn optional research content into mandatory
  fields.
- Present the Brainstorm to the user as a complete document-style HTML page,
  not an expanded data card.

The authority flow is:

```text
standalone Brainstorm + iterative refinement
  -> explicit user approval
  -> PackageDraftCreated consumes the exact Brainstorm revision
  -> research-package owns Draft refinement and finalization
```

The Brainstorm CLI writes events and content-addressed NoteRefs through the
research-op gateway. The Dashboard renderer owns HTML projection. Never edit
`.research/interface/`, state logs, or `current.json` by hand.

## Load bounded context

Start with:

- the user's rough idea;
- the active Project goal and out-of-scope boundary;
- related Learnings and Rules from state queries;
- verified paper, repository, metric, and dataset facts needed by the draft.

Before research ideation or method design, load relevant project Research Wiki
Reviews, Paper Notes, and source PDFs when the `research-wiki` skill is
available. Treat source discovery as evidence gathering, not permission to
invent novelty or state-of-the-art claims.

Resolve all workspace data through `ResearchPaths`. `RESEARCH_ROOT` defaults to
`.research`; `--research-root` is the only path override.

Check the Project boundary:

```bash
python3 skills/research-brainstorm/scripts/brainstorm.py check-project \
  --workspace <workspace>
```

If `active_project_ids` is empty, stop and use `research-onboard` or
`research-scope`. Do not read generated interface files as research context.

## Keep one direction in one document

Before creating state, identify the core research question and decision path.
Place dependent stages, alternatives, risks, ablations, datasets, and open
questions in one document when they support that same question.

Create multiple Brainstorms only when the candidate directions can be accepted
or rejected independently and need independent evaluation contracts and
lifecycle decisions. Show the split rationale and obtain user confirmation
before creating more than one record. When uncertain, keep one Brainstorm.

## Author the document

Read [references/document-contract.md](references/document-contract.md) before
creating or materially restructuring a Brainstorm document.

The renderer supplies the stable shell:

- Title;
- Abstract / TLDR;
- Idea Snapshot;
- generated Table of Content;
- free-form detailed body;
- status, revision, timestamps, and provenance.

The author supplies an HTML body fragment with arbitrary meaningful Sections,
tables, figures, formulas, code, callouts, and references. The document
contract defines reusable semantic classes without prescribing Section names.

Create one Brainstorm:

```bash
python3 skills/research-brainstorm/scripts/brainstorm.py add \
  --workspace <workspace> \
  --title "Candidate-pool audit" \
  --idea "Measure first-stage visibility before changing the reranker" \
  --abstract "Test whether the candidate pool, rather than reranking, is the bottleneck." \
  --snapshot '[{"label":"Core question","value":"Is the target visible at K?"}]' \
  --body-file /tmp/brainstorm-body.html \
  --lit-refs '["paper:example"]'
```

`--body-file` accepts an HTML fragment, not a complete HTML document. The CLI
validates it, stores it as a NoteRef, and the shared renderer wraps it in the
general template.

Revise the same record:

```bash
python3 skills/research-brainstorm/scripts/brainstorm.py revise \
  --workspace <workspace> --id <idea-id> \
  --patch '{"rough_metric":"CanHit@100 and R@10"}' \
  --abstract "Updated TLDR" \
  --body-file /tmp/revised-brainstorm-body.html
```

A revision advances the Brainstorm aggregate version and `revision`; it does
not create a Package. Package `draftRevision` begins only after conversion.

## Merge or archive fragments

When existing Brainstorms represent stages of one direction:

1. choose one ACTIVE canonical Brainstorm;
2. merge the useful content into that document;
3. revise the canonical record;
4. finalize subordinate documents before archiving them;
5. archive each subordinate with a reason and `--merged-into <canonical-id>`;
6. preserve links and history in the generated archived pages.

```bash
python3 skills/research-brainstorm/scripts/brainstorm.py remove \
  --workspace <workspace> --id <fragment-id> \
  --merged-into <canonical-id> \
  --reason "merged as the reproduction stage"
```

Archived Brainstorms remain readable audit records. An explicit user may
discard an archived duplicate from the current catalogue, while its event
history remains intact. Conversion is not archival: the approved document is
transferred into the new Draft Package in the same event that consumes the
standalone Brainstorm.

## Rebuild and verify the human surface

Every create, revise, or archive command attempts an atomic interface rebuild.
State remains authoritative if projection fails, but a user-facing Brainstorm
task is not visually complete until the card and detail document render.

```bash
python3 skills/research-dashboard/scripts/ensure_dashboard.py \
  --workspace <workspace> build
```

Verify that:

- the Brainstorm card appears when the Brainstorm lane is selected;
- Brainstorm and Draft Package cards appear as distinct lifecycle objects;
- the detail route returns the generated full document;
- the ToC resolves document headings;
- `ACTIVE` and `ARCHIVED` Brainstorm semantics are visible;
- desktop and mobile layouts do not overflow.

Report the interface-relative `detailPath` separately from the actual server
listen URL or any SSH/IDE forwarded URL. Do not hardcode a port.

## Convert only on explicit request

Do not create a Draft Package merely because the Brainstorm looks complete.
After the user explicitly approves the audited revision, route to
`research-package` and convert it:

```bash
python3 skills/research-package/scripts/draft_package.py \
  --workspace <workspace> convert \
  --brainstorm-id <brainstorm-id> \
  --actor-id <stable-user-id>
```

`PackageDraftCreated` verifies the exact Brainstorm version and NoteRef,
transfers that document to `docs/proposal.html`, removes the standalone
Brainstorm from current state, and creates a non-executable `DRAFT / REFINING`
Package. This is the first approval boundary. Direction and Experiment design
belongs to the later Draft Package review, not to this conversion decision.

## Boundaries

- Do not create multiple Brainstorms just because one idea has several stages.
- Do not create a Draft Package before explicit conversion approval.
- Do not derive or commit Direction and Experiment Scope during Brainstorm conversion.
- Do not make typed Direction fields mandatory in the free-form draft.
- Do not store candidate files, rankings, or verdicts in ad hoc workspace
  directories.
- Do not hand-author a complete page or copy template CSS into every NoteRef.
- Do not treat a path found on disk as a ready dataset until its split,
  manifest, corpus mapping, and project integration are verified.

## Done condition

Before conversion, the requested idea exists as one standalone Brainstorm, its
body is a valid NoteRef, and its generated page contains the stable shell plus
the authored free-form content. After explicit conversion, that Brainstorm is
absent from current state and one `DRAFT / REFINING` Package owns the same
document at `docs/proposal.html`. No Scope or execution authority is created by
this skill.
