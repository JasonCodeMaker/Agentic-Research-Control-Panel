"""Self-evolve Rule Store (v1) — typed in-context anti-regression + recipe-rule memory.

Pure, node-free libraries (schema / lifecycle / store / oracles / induce). All
authoritative writes go through research-op `evolution-*`; nothing here touches disk
except the append-only store log. See plan/2026-06-04-self-evolving-self-learning-research.md.
"""
