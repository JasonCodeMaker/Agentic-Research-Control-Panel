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
    assert "The agent proposes; the PM decides." in text
    assert "**Scope Review**" in text
    assert "Triage Item: <item-id>" in text
    assert "Proposal Hash: <proposal-hash>" in text
    assert "Next Step:" in text
    assert "`ACCEPT <item-id> <proposal-hash>`" in text
    assert "`REJECT <item-id> <proposal-hash>`" in text
    assert "`REVISE <item-id> <proposal-hash>`" in text
    assert "--op scope-transition" in text
    assert "--from-triage <item-id>" in text
    assert "`experiment` | `purpose`, `config_ref`, `gate`, `control_mode`" in text
    assert ".research/state" in text
    assert ".research/interface" in text


def test_skill_allows_delegated_execution_after_explicit_pm_decision():
    text = SKILL.read_text(encoding="utf-8")
    assert "`ACCEPT <item-id> <proposal-hash>` authorizes the `ACCEPTED` disposition" in text
    assert "`REJECT <item-id> <proposal-hash>` authorizes only the `REJECTED`" in text
    assert "`REVISE <item-id> <proposal-hash>` authorizes a validated replacement" in text
    assert "Record the accepted disposition with `triage.py dispose`." in text
    assert "Without an explicit PM decision, stop here." in text
    assert "Never invoke git." in text


def test_skill_defines_safe_decision_branches_and_bound_reply_checks():
    text = SKILL.read_text(encoding="utf-8")
    contract = " ".join(text.split())
    assert "The item id and hash must match the exact proposal visible to the PM." in contract
    assert "A stale hash, ambiguous reply, or missing decision leaves the proposal pending." in contract
    assert "### Accept" in text
    assert "### Reject" in text
    assert "### Revise" in text


def test_skill_defines_same_id_revise_replacement_without_scope_write():
    text = SKILL.read_text(encoding="utf-8")
    assert "submit a replacement under the same item id" in text
    assert "Show the replacement in full with its new hash." in text
    assert "Do not dispose the old view or" in text
    assert "invoke the Scope writer for `REVISE`." in text


def test_delegated_triage_execution_requires_hash_bound_snapshot_path():
    scope_text = SKILL.read_text(encoding="utf-8")
    research_op_text = RESEARCH_OP_SKILL.read_text(encoding="utf-8")
    scope_contract = " ".join(scope_text.split())

    assert (
        "Delegated execution of a ratified Triage proposal must use "
        "`--from-triage <item-id>`."
    ) in scope_contract
    assert "--from-triage <proposal-id>" in research_op_text
    assert "Prefer the accepted Triage item" not in scope_text
    assert "preferably `--from-triage" not in research_op_text
    _assert_explicit_payload_governance(scope_text, research_op_text)


def test_formal_scope_concepts_use_experiment_not_task():
    text = SKILL.read_text(encoding="utf-8")
    assert "project|direction|experiment" in text
    assert "level=experiment" not in text
    assert "Task Scope" not in text
    assert "Task/Milestone" not in text
