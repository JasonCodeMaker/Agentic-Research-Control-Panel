from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "research-scope" / "SKILL.md"
RESEARCH_OP_SKILL = ROOT / "skills" / "research-op" / "SKILL.md"
RESEARCH_OP_COMPAT = (
    ROOT / "skills" / "research-op" / "references" / "compatibility-scope.md"
)


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
    assert "The agent prepares the semantic review" in contract
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
    contract = " ".join(text.split())
    assert "An explicit user confirmation authorizes the exact Draft" in text
    assert "commit-scope" in text
    assert "one `TransactionCommitted` event or nothing" in contract
    assert "Record `REJECTED` through `triage.py dispose`" in text
    assert "submit a replacement under the same proposal id" in text
    assert "do not ask the user to approve again" in contract


def test_skill_defines_safe_decision_branches_and_bound_reply_checks():
    text = SKILL.read_text(encoding="utf-8")
    contract = " ".join(text.split())
    assert "Review digests and, on the compatibility path, item ids and proposal hashes remain internal bindings" in contract
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
    research_op_text = "\n".join(
        (
            RESEARCH_OP_SKILL.read_text(encoding="utf-8"),
            RESEARCH_OP_COMPAT.read_text(encoding="utf-8"),
        )
    )
    scope_contract = " ".join(scope_text.split())

    assert "package_finalization` proposal cannot use this path" in scope_contract
    assert "ordinary `scope-accept`" in scope_contract
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


def test_skill_defines_evidence_contract_decomposition():
    text = SKILL.read_text(encoding="utf-8")
    contract = " ".join(text.split())
    reference = (
        ROOT
        / "skills"
        / "research-scope"
        / "references"
        / "experiment-decomposition.md"
    ).read_text(encoding="utf-8")

    assert "smallest independently governable evidence contract" in contract
    assert "never assume a fixed count" in contract
    assert (
        "record-only characterization uses an evidence-completeness gate"
        in contract.lower()
    )
    assert "decision ledger" in reference
    assert "hard split test" in reference
    assert "merge test" in reference
    assert "Seeds, retries, and repeated executions become Runs." in reference
    assert "No performance threshold was introduced into record-only work." in reference


def test_scope_freezes_a_reviewed_draft_instead_of_creating_the_authoring_shell():
    text = SKILL.read_text(encoding="utf-8")
    contract = " ".join(text.split())
    assert "Scope is therefore a commit boundary, not an early authoring form." in contract
    assert '"draft_revision": 3' in text
    assert '"document_sha256": "<reviewed-document-hash>"' in text
    assert "If the draft changes after the visible review" in contract
    assert "TransactionCommitted" in text
