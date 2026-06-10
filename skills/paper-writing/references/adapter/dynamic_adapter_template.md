# Template: Dynamic Paper Adapter

The reviewable, human-gated writing rules for one paper project + target venue. Emitted by
`scripts/generate_adapter.py`; validated by `scripts/validate_adapter.py`.

Required sections (validator checks each is present):

```
# Dynamic Paper Adapter: <paper_id>
## P0 — Hard Preserve              facts, citations, math, notation, numbers, names, locked claims
## P2 — Target-Venue Patterns      observed corpus conventions (or venue hints if no corpus)
## P3 — Secondary / Exemplar Patterns
## P4 — Active Profile Fallback     references/workflow_kernel/profiles/<profile>.md
## P5 — Cleanup Rules               AI-taste / overclaim / empty-transition removal
## Conflict Table                   target-corpus wins over global guide defaults (P2 > P3)
## Section-Specific Guidance
## Cautions & Human-Review Notes
```

Precedence: P0 > P1(kernel) > P2 > P3 > P4 > P5. The adapter never overrides P0 or the kernel stage
order. It is a PROPOSAL until a human confirms the gate in `adapter_review.md`.
