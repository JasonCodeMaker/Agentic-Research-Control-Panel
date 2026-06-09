"""Fork-altitude contract: the conversational front-door / orchestration skills must run RESIDENT
(no `context: fork`) so the live session keeps loop state and never goes inert on a user-typed
`/slash` (the "No response requested." halt). Bounded worker/mutator skills stay forked for context
isolation (核心问题 #1). See [[auto-research-harness-first-strategy]] and the session-b07d0f85 diagnosis.
"""

import re
from pathlib import Path

_PIPE = Path(__file__).resolve().parents[2]
_SKILLS = _PIPE / "skills"

# Resident: a human converses with these / they drive a continuing loop — forking breaks continuity.
RESIDENT = {"research-auto", "research-onboard", "research-brainstorm", "research-scope"}
# Forked: bounded "do one task, return a result" executors — isolation is desirable.
FORKED = {"research-op", "research-lit", "research-ideate", "research-reflect", "research-apply"}


def _frontmatter(skill_name):
    text = (_SKILLS / skill_name / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, f"{skill_name}/SKILL.md has no YAML frontmatter"
    return m.group(1)


def _declares_fork(skill_name):
    return re.search(r"^context:\s*fork\s*$", _frontmatter(skill_name), re.M) is not None


def test_resident_skills_do_not_fork():
    forked = sorted(s for s in RESIDENT if _declares_fork(s))
    assert forked == [], f"these front-door skills must run resident (drop `context: fork`): {forked}"


def test_bounded_workers_still_fork():
    not_forked = sorted(s for s in FORKED if not _declares_fork(s))
    assert not_forked == [], f"these bounded workers must keep `context: fork`: {not_forked}"
