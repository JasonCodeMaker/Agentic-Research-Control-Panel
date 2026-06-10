# Guide: Experiments / Evaluation

## Role
Validate each introduction claim with controlled evidence.

## Move sequence
1. **Setup anchoring** — datasets, metrics, baselines, implementation details (optimizer, LR, hardware, seeds).
2. **Head-to-head** — main results table with all baselines; bold the best; note significance if applicable.
3. **Deep dive** — analysis: what do the numbers mean?
4. **Takeaway synthesis** — each experiment cluster ends with a takeaway paragraph tied to a claim.
5. **Ablation** — remove one component at a time; each ablation tests one design decision.
6. **Robustness** — sensitivity, failure modes, where the method breaks.

## Rules
- Every claim in Abstract/Introduction maps to a subsection here.
- Report secondary metrics, not accuracy alone.
- Interpret figures: "Figure 3 shows X, confirming Y", never "see Figure 3".

## Do not
- Report only accuracy; cherry-pick qualitative examples without quantitative support; omit hyperparameters.

## Paragraph roles to expect
evidence paragraphs (claim-first), each closing experiment cluster with a takeaway.
