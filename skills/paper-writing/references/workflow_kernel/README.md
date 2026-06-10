# Workflow Kernel (L1)

The kernel owns the **domain-neutral** paper lifecycle. It decides *which writing action is legal
next*; it does **not** carry venue conventions. All venue/style defaults live in `profiles/`.

- [`stages.md`](stages.md) — the six lifecycle stages and the default section order (introduction-twice).
- [`profiles/`](profiles/) — replaceable venue conventions. Default: `ml_dl_general.md`.

Rule the kernel enforces:

```
Use the active profile's venue conventions.
If no profile is selected, use ml_dl_general.md.
```

The kernel is implemented by `scripts/workflow_kernel.py` (`STAGES`, `SECTION_ORDER`,
`next_stage`, `is_legal_next`, `resolve_profile`, `build_plan`).
