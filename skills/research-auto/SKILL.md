---
name: research-auto
description: "Deprecated compatibility alias for /research-run. Use only when the user types the old /research-auto command; immediately redirect to /research-run for running, continuing, monitoring, verifying, or completing an existing scoped research package."
disable-model-invocation: false
---

# research-auto

`/research-auto` is a deprecated compatibility alias. Use `/research-run` instead.

Do not run a separate procedure from this skill. The execution controller, scripts, tests, and package
completion contract now live in `skills/research-run/`.

When invoked, respond with the redirect and then continue under `/research-run` if the user intended to
run or complete a package.
