# Lifecycle Stages (domain-neutral)

The kernel enforces six stages in order. Each stage gates the next.

| # | Stage | Gate to enter |
| --- | --- | --- |
| 1 | context | `paper.yaml` has an identity sentence and at least one contribution claim. |
| 2 | plan | `context/paper_context.md` exists; section outline with claim assignments produced. |
| 3 | section_drafts | A confirmed plan and (if a corpus venue adapter is used) a confirmed adapter. |
| 4 | integration | All planned sections drafted. |
| 5 | compression | Cross-section consistency pass complete. |
| 6 | presubmission | Manuscript compiled to PDF (for mechanical checks). |

## Default section order — the introduction-twice rule

```
Draft-0 Introduction   (disposable framing scaffold; sets evaluation guardrails)
  -> Evaluation / Results
  -> Method / Design
  -> Background (only if needed)
  -> Related Work
  -> Final Introduction (rewritten from scratch after evaluation)
  -> Abstract
  -> Conclusion
```

The introduction is written **twice**. Draft-0 clarifies what the paper is *trying* to show before the
experiments are designed; the final introduction promises exactly what the evidence supports.

The final introduction's structure may be reshaped by the active profile or venue adapter, but the
introduction-twice ordering itself stays in the kernel.

## Profile selection

```
Use the active profile's venue conventions.
If no profile is selected, use profiles/ml_dl_general.md.
```

The kernel never hardcodes a venue. Per-section scaffolding rule (kernel-level, profile-agnostic):
write the topic sentences first, verify they form a coherent argument, then fill paragraphs.

## Figure handling (kernel-level)

- **Data figure** (needs experimental data to render): owned by result/evaluation tooling.
- **Non-data figure** (architecture, pipeline, taxonomy, concept, comparison schematic): owned by
  paper-writing figure synthesis — `spec -> generate -> critique`.
