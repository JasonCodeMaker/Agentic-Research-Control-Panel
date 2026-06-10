# Guide: Reviewer Self-Check

Run before submission. Answer as a skeptical reviewer; resolve every high-risk item.

## Five dimensions
1. **Contribution** — Is the contribution clear, specific, and verifiable? Could a reader state it in one sentence?
2. **Writing clarity** — One message per paragraph? Topic sentences assert claims? Terminology stable?
3. **Experimental strength** — Right baselines? Enough datasets? Ablations isolate one variable each?
4. **Evaluation completeness** — Does every introduction claim have a matching experiment? Secondary metrics reported?
5. **Method soundness** — Notation defined? Design choices justified? No unproven claim stated as proved?

## Hard constraints
- Claim-evidence alignment is non-negotiable for Abstract and Introduction.
- If a claim cannot be supported by results, weaken or remove it.
- Adversarial pass: list the reviewer's top-3 rejection risks and address each explicitly.

## Output
A five-row checklist (one row per dimension) with status and the unresolved items, followed by the
revisions those items require.
