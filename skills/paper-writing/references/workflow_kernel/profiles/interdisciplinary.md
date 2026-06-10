# Profile: Interdisciplinary / Applied ML

For papers that apply ML to another field (biology, health, climate, social science, materials) or
target a domain venue with mixed ML and domain readership.

## Reader model

- The reader is half ML, half domain expert. Define ML jargon for the domain reader and domain jargon
  for the ML reader. Never assume both literacies in the same sentence.

## Framing

- Lead with the **domain problem and stakes**, then the ML contribution. The ML method is a means;
  the domain result is the headline.
- State domain-validity explicitly: data provenance, label quality, distribution shift, and what a
  domain expert would accept as evidence.

## Evidence discipline

- Keep the ML evidence discipline from `ml_dl_general.md` (baselines, ablations, reproducibility).
- Add domain-appropriate validation (e.g., expert review, established domain metric, held-out cohort).
- Calibrate claims to domain consequences, not just benchmark deltas.

Defers to `ml_dl_general.md` for voice and contribution framing. A target-venue corpus adapter (P2)
overrides these defaults when present.
