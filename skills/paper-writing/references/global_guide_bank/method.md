# Guide: Method / Design

## Role
Present the approach so a reader can understand and reproduce it. Intuition before formalism.

## Move sequence (per module)
1. **Module motivation** — what gap this module closes (tie back to the introduction's problem gap).
2. **Design** — the mechanism, intuition first, then notation.
3. **Technical advantage** — why this design beats the obvious alternative ("we use X instead of Y because…").

## Skeleton
overview paragraph (the pipeline in 4–6 sentences) → one figure of the architecture/pipeline →
module 1 (motivation/design/advantage) → module 2 → … → training/inference details.

## Rules
- Define all notation before first use; keep it consistent throughout.
- Justify every non-obvious design choice immediately.
- One overview figure of the architecture/pipeline is expected (a non-data figure).

## Do not
- Write the method as a list of patches on a naive baseline.
- Introduce notation in an equation before naming it in prose.

## Paragraph roles to expect
method (design) and advantage paragraphs, each opening with the design claim it defends.
