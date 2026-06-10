# Template: Section Revision Log

One entry per changed paragraph during `revise`. Emitted by `scripts/section_audit.write_revision_log`.

```
## <section>
- rule: <rule applied> — source: target-corpus | secondary-corpus | user-exemplar | profile | cleanup
  - preserved verbatim: <citations, equations, notation, numbers kept unchanged>
```

Every entry records which rule was applied, its source layer (P0–P5), and what P0 content was
preserved verbatim. The log is the audit trail proving no facts changed during revision.
