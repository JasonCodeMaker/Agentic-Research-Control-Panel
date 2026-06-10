# Template: Paper Style Card

A style card describes **structure and statistics only** — never corpus prose. Emitted by
`scripts/generate_adapter.py` per converted corpus paper.

```
## Paper Style Card: <paper_id>

- corpus role: primary_target | secondary_field | user_exemplar
- avg sentence length (words): <n>
- voice: active-dominant | passive-dominant
- hedging level: low | medium | high
- math density: light | moderate | heavy
- numbered contributions: true | false
- standalone related work: true | false
- observed section order: <H1 > H2 > ...>
- what this paper does NOT do: <absent structural patterns>
```

Hard rule: no quotes, no paraphrases, no reproduced findings. Only structural facts and counts.
