# Profile: ML / DL General (default)

The default profile for machine-learning / deep-learning papers. Preserves the kernel's claim-first
discipline without any systems/networking surface conventions. Covers method, benchmark/dataset,
empirical, theory-adjacent, safety/eval, and interdisciplinary ML papers.

## Contribution framing

- **Method papers**: contribution = a named mechanism + the measured effect. "X reduces error 13× on D",
  not "we propose a novel X". 3 contributions maximum; each is one concrete, verifiable claim.
- **Benchmark / dataset papers**: contribution = the resource + what it measures that prior resources
  cannot + at least one finding the resource enables. Document construction, splits, and licensing.
- **Empirical analysis papers**: contribution = the question + the controlled comparison + the takeaway.
  State the hypothesis before the result.
- **Theory-adjacent papers**: separate proved claims from empirically-observed ones. Never present an
  empirical regularity in the grammar of a theorem.

## Evidence discipline

- Every Abstract/Introduction claim maps to an experiment subsection (claim-evidence is a hard gate).
- Baseline and SOTA comparison is mandatory; results without a baseline are not claims.
- Ablations remove one component at a time — each ablation tests exactly one design decision.
- Report secondary metrics, not accuracy alone. State seeds, optimizer, LR, and hardware for reproducibility.
- Put implementation detail where a replicator needs it (setup paragraph or appendix), not in the method prose.

## Claim calibration & hedging

- **Bounded hedging** is allowed only for uncertain *mechanism explanations* ("this likely reflects …").
  Empirical results stay assertive: "X achieves 47.3", never "X may achieve".
- Limitations and failure modes are stated proactively, in their own paragraph — not buried or omitted.
- Theory claims are calibrated to what is proved; empirical claims to what is measured.

## Voice

- Claim-first topic sentences. Active voice. ~21-word mean sentence length.
- Define every term on first use; then use it consistently (no synonyms for the method name).
- Interpret figures, do not just cite them: "Figure 3 shows X, confirming Y."
- Banned self-descriptions before evidence: "novel", "significant", "state-of-the-art", "comprehensive",
  "robust", "substantial", "extensive experiments demonstrate".

## Venue variations (ML/DL conferences)

| Venue | Notable conventions |
| --- | --- |
| NeurIPS / ICML / ICLR | Reproducibility checklist; integrated or standalone related work (pick one); broader-impact where required. |
| ACL / EMNLP / NAACL | Limitations section is mandatory; responsible-NLP/ethics statement; dataset/annotation detail. |
| CVPR / ICCV / ECCV | Teaser figure on page 1; qualitative results expected alongside quantitative; supplementary for extra results. |

When a target-venue corpus adapter exists (P2), its observed conventions override this profile's
generic defaults — but never override P0 facts or the kernel's stage order.
