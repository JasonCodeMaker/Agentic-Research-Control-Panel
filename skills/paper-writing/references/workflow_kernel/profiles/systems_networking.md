# Profile: Systems / Networking

The systems/networking conventions extracted out of the original kernel so they no longer leak into
ML/DL papers. Select this profile **only** for systems/networking venues.

## Paragraph labeling

- Use `\smartparagraph{}` labels to head each paragraph with its claim.

## Venue defaults

- Target venues: NSDI, SIGCOMM, CoNEXT, IMC, OSDI, SOSP.
- **NSDI / SIGCOMM / IMC**: systems evaluation emphasis — latency, throughput, memory, deployment
  topology. Frame contributions as operational impact (what an operator can now do).
- Place Related Work **after** the evaluation.

## Evaluation emphasis

- Lead the evaluation with systems metrics: latency, throughput, memory footprint, tail behavior,
  deployment cost. Anchor each experiment to a deployment scenario.

## Hedging

- Absolute zero-hedging policy: every sentence asserts. No "may", "could", "we believe".

## Figure archetypes

- Systems-specific figure defaults: deployment topology diagrams, dataflow pipelines, testbed diagrams.

These rules are intentionally quarantined here. The ML/DL general profile (`ml_dl_general.md`) and the
domain-neutral kernel (`stages.md`) must never contain them.
