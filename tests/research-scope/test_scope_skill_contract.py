from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "research-scope" / "SKILL.md"
RESEARCH_OP_SKILL = ROOT / "skills" / "research-op" / "SKILL.md"


def _assert_explicit_payload_governance(scope_text: str, research_op_text: str) -> None:
    scope_contract = " ".join(scope_text.split())
    research_op_contract = " ".join(research_op_text.split())

    assert "explicit payload form is reserved for separately governed" in scope_contract
    assert "cannot substitute for or bypass the accepted snapshot" in scope_contract
    assert "explicit payload form is reserved for separately governed" in research_op_contract
    assert "accepted proposal" in research_op_contract
    assert "recomputes its content hash" in research_op_contract


def test_skill_requires_clear_scope_review_and_next_step():
    text = SKILL.read_text(encoding="utf-8")
    contract = " ".join(text.split())
    assert "The agent may submit a proposal" in contract
    assert "**Scope review**" in text
    assert "CONFIRM/确认" in text
    assert "Do not require the user to copy an item id or hash." in text
    assert "--op scope-accept" in text
    assert "--proposal-hash <proposal-hash>" in text
    assert "--op scope-transition" in text
    assert "--from-triage <proposal-id>" in text
    assert "`experiment` | `purpose`, `config_ref`, `gate`, `control_mode`" in text
    assert ".research/state" in text
    assert ".research/interface" in text
    assert "Candidate, not yet submitted" not in text
    assert "Triage Item:" not in text
    assert "Proposal Hash:" not in text


def test_skill_allows_delegated_execution_after_explicit_pm_decision():
    text = SKILL.read_text(encoding="utf-8")
    assert "An explicit user confirmation authorizes both the `ACCEPTED` disposition" in text
    assert "Record `REJECTED` through `triage.py dispose`" in text
    assert "submit a replacement under the same proposal id" in text
    assert "do not ask the user to approve again" in text


def test_skill_defines_safe_decision_branches_and_bound_reply_checks():
    text = SKILL.read_text(encoding="utf-8")
    contract = " ".join(text.split())
    assert "The item id and hash remain internal bindings to the exact proposal visible to the user." in contract
    assert "Treat a generic, stale, conflicting, or multiply bound reply as ambiguous." in contract
    assert "### Accept" in text
    assert "### Reject" in text
    assert "### Revise" in text


def test_skill_defines_same_id_revise_replacement_without_scope_write():
    text = SKILL.read_text(encoding="utf-8")
    assert "submit a replacement under the same proposal id" in text
    assert "Show the replacement once." in text
    assert "Do not accept or commit the old snapshot." in text


def test_delegated_triage_execution_requires_hash_bound_snapshot_path():
    scope_text = SKILL.read_text(encoding="utf-8")
    research_op_text = RESEARCH_OP_SKILL.read_text(encoding="utf-8")
    scope_contract = " ".join(scope_text.split())

    assert "ordinary conversational approval uses `scope-accept`" in scope_contract.lower()
    assert "--from-triage <proposal-id>" in research_op_text
    assert "Prefer the accepted Triage item" not in scope_text
    assert "preferably `--from-triage" not in research_op_text
    _assert_explicit_payload_governance(scope_text, research_op_text)


def test_formal_scope_concepts_use_experiment_not_task():
    text = SKILL.read_text(encoding="utf-8")
    assert "Project -> Direction -> Experiment" in text
    assert "level=experiment" not in text
    assert "Task Scope" not in text
    assert "Task/Milestone" not in text
