# Template: Style Profile

Aggregates the per-paper style cards into the dominant observed patterns for one writing destination.
Emitted by `scripts/generate_adapter.py`.

```
# Style Profile: <venue>
Generated from <N> papers.

- voice: <dominant>
- hedging level: <dominant>
- math density: <dominant>
- numbered contributions: <true|false>
- standalone related work: <true|false>
```

Patterns here feed P2 of the dynamic adapter and the conflict table (target corpus beats global guide
defaults). Structure only — no corpus prose.
