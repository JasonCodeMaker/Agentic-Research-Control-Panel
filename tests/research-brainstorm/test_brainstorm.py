"""State-backed Brainstorm documents and explicit Direction promotion."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-brainstorm" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "research-package" / "scripts"))

import brainstorm  # noqa: E402
import draft_package  # noqa: E402
import scope_ssot  # noqa: E402
from lib.interface import build_interface  # noqa: E402
from lib.research_state import (  # noqa: E402
    CommandRejected,
    EventStore,
    ResearchPaths,
    StateQuery,
    UpgradeRequired,
)
from tests.scope_fixtures import direction_spec, project_spec  # noqa: E402


# --- idea store (brainstorms.js) ------------------------------------------

def test_read_empty_when_absent(tmp_path):
    with pytest.raises(UpgradeRequired):
        brainstorm.read_brainstorms(tmp_path)
    assert not (tmp_path / ".research").exists()


def test_add_assigns_id_and_roundtrips(tmp_path):
    bid = brainstorm.add_brainstorm(tmp_path, {"title": "Mixup helps", "idea": "augment with mixup"})
    items = brainstorm.read_brainstorms(tmp_path)
    assert [i["id"] for i in items] == [bid]
    assert items[0]["title"] == "Mixup helps"
    assert "created_at" in items[0]
    assert items[0]["status"] == "ACTIVE"
    assert items[0]["revision"] == 1
    assert "lifecycle" not in items[0]
    events = EventStore(ResearchPaths.resolve(workspace=tmp_path, environ={})).events()
    assert events[-1]["event_type"] == "BrainstormCreated"


def test_interface_builder_generates_english_detail_page(tmp_path):
    bid = brainstorm.add_brainstorm(
        tmp_path,
        {
            "title": "Candidate pool audit",
            "idea": "Compare stage-1 GT visibility against reranker conversion.",
            "rough_metric": "CanHit@100 and X-Pool R@10",
            "lit_refs": ["local candidate CSV"],
            "created_at": "2026-06-10T00:00:00+00:00",
        },
    )
    item = brainstorm.read_brainstorms(tmp_path)[0]
    assert item["id"] == bid
    assert item["detailPath"] == "brainstorm/2026-06-10-candidate-pool-audit.html"

    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    page = paths.interface / item["detailPath"]
    assert not page.exists()
    build_interface(paths)
    assert page.exists()
    html = page.read_text(encoding="utf-8")
    assert '<html lang="en">' in html
    assert 'data-page="brainstorm-document"' in html
    assert '<link rel="stylesheet" href="../assets/brainstorm.css">' in html
    assert "Abstract / TLDR" in html
    assert "Idea Snapshot" in html
    assert "data-docs-toc" in html
    assert "Candidate pool audit" in html
    assert "Compare stage-1 GT visibility against reranker conversion." in html
    assert "CanHit@100 and X-Pool R@10" in html
    assert "local candidate CSV" in html
    assert "<style>" not in html
    package_data = (paths.interface / "data" / "research-packages.js").read_text(
        encoding="utf-8"
    )
    legacy_data = (paths.interface / "data" / "brainstorms.js").read_text(
        encoding="utf-8"
    )
    assert '"id": "candidate-pool-audit"' not in package_data
    assert '"id": "candidate-pool-audit"' in legacy_data


def _document_body(label: str) -> str:
    return f"""
<section class="doc-section" id="core-question">
  <h2><span class="section-number">01 </span><span>{label}</span></h2>
  <p>Keep the core question observable.</p>
</section>
<section class="doc-section wide" id="comparison">
  <h2><span class="section-number">02 </span><span>Comparison</span></h2>
  <div class="table-wrap"><table class="doc-table">
    <caption>Candidate stages</caption>
    <thead><tr><th scope="col">Stage</th><th scope="col">Question</th></tr></thead>
    <tbody><tr><td>Reproduction</td><td>Does the baseline run?</td></tr></tbody>
  </table></div>
  <figure class="research-figure"><figcaption>Figure 1. One governed document.</figcaption></figure>
</section>
""".strip()


def test_add_stores_free_form_document_note_and_renders_shared_shell(tmp_path):
    body = _document_body("Core question")
    bid = brainstorm.add_brainstorm(
        tmp_path,
        {
            "id": "one-direction",
            "title": "One broad direction",
            "idea": "Unify related stages.",
            "abstract": "One revisable proposal for the shared core question.",
            "idea_snapshot": [
                {"label": "Core question", "value": "Can the same mechanism transfer?"},
                {"label": "Current state", "value": "Draft"},
            ],
            "document_html": body,
            "page_language": "en",
        },
    )

    item = brainstorm.read_brainstorms(tmp_path)[0]
    assert item["id"] == bid
    assert "document_html" not in item
    note = item["document_note"]
    assert note["mime"] == "text/html;profile=brainstorm-fragment"
    note_path = tmp_path / ".research" / note["uri"]
    assert note_path.read_text(encoding="utf-8") == body

    build_interface(ResearchPaths.resolve(workspace=tmp_path, environ={}))
    page = tmp_path / ".research" / "interface" / item["detailPath"]
    rendered = page.read_text(encoding="utf-8")
    assert "One revisable proposal for the shared core question." in rendered
    assert "Can the same mechanism transfer?" in rendered
    assert "Candidate stages" in rendered
    assert "Figure 1. One governed document." in rendered
    assert 'data-page="brainstorm-document"' in rendered
    assert "Revision 1" in rendered


def test_revise_updates_same_brainstorm_document_in_place(tmp_path):
    bid = brainstorm.add_brainstorm(
        tmp_path,
        {
            "id": "same-draft",
            "title": "Same draft",
            "idea": "Initial framing",
            "document_html": _document_body("Initial section"),
        },
    )
    first = brainstorm.read_brainstorms(tmp_path)[0]
    first_sha = first["document_note"]["sha256"]

    brainstorm.revise_brainstorm(
        tmp_path,
        bid,
        {
            "abstract": "Refined after user audit.",
            "document_html": _document_body("Revised section"),
        },
    )

    items = brainstorm.read_brainstorms(tmp_path)
    assert [item["id"] for item in items] == [bid]
    assert items[0]["document_note"]["sha256"] != first_sha
    assert items[0]["abstract"] == "Refined after user audit."
    assert items[0]["revision"] == 2
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    assert StateQuery(paths).brainstorms()["data"]["versions"][bid] == 2
    build_interface(paths)
    rendered = (paths.interface / items[0]["detailPath"]).read_text(encoding="utf-8")
    assert "Revised section" in rendered
    assert "Initial section" not in rendered
    assert "Revision 2" in rendered


@pytest.mark.parametrize(
    "body",
    [
        "<!doctype html><html><body><h2>Full page</h2></body></html>",
        "<section><h2>Executable</h2><script>alert(1)</script></section>",
        "<section><p>No section heading</p></section>",
        '<section onclick="alert(1)"><h2>Handler</h2></section>',
    ],
)
def test_document_fragment_rejects_shell_and_executable_markup(tmp_path, body):
    with pytest.raises(ValueError):
        brainstorm.add_brainstorm(
            tmp_path,
            {"title": "Invalid body", "idea": "x", "document_html": body},
        )
    assert brainstorm.read_brainstorms(tmp_path) == []


def test_archive_can_link_a_merged_fragment_to_canonical_brainstorm(tmp_path):
    canonical = brainstorm.add_brainstorm(
        tmp_path,
        {"id": "canonical", "title": "Canonical", "idea": "whole direction"},
    )
    fragment = brainstorm.add_brainstorm(
        tmp_path,
        {"id": "fragment", "title": "Fragment", "idea": "one stage"},
    )

    assert brainstorm.remove_brainstorm(
        tmp_path,
        fragment,
        reason="merged as the migration stage",
        merged_into=canonical,
    )
    archived = next(
        item
        for item in brainstorm.read_brainstorms(tmp_path, include_archived=True)
        if item["id"] == fragment
    )
    assert archived["status"] == "ARCHIVED"
    assert archived["merged_into"] == canonical
    build_interface(ResearchPaths.resolve(workspace=tmp_path, environ={}))
    rendered = (
        tmp_path / ".research" / "interface" / archived["detailPath"]
    ).read_text(encoding="utf-8")
    assert "Archived stage record" in rendered
    assert "merged as the migration stage" in rendered
    assert canonical in rendered
    assert 'href="./' in rendered and "canonical.html" in rendered


def test_skill_contract_keeps_one_free_form_document_until_materialization():
    skill = (ROOT / "skills" / "research-brainstorm" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    contract = (
        ROOT / "skills" / "research-brainstorm" / "references" / "document-contract.md"
    ).read_text(encoding="utf-8")
    assert "One broad research direction maps to one Brainstorm by default" in skill
    assert "Refine the same Brainstorm in place" in skill
    assert "user has asked to continue into Package design" in skill
    assert "Keep the body free-form" in skill
    assert "standalone Brainstorm + iterative refinement" in skill
    assert "DRAFT_MATERIALIZE records Brainstorm provenance" in skill
    assert "Scope or execution authority is created by this skill" in skill
    assert "not a research schema" in contract


def test_add_dedupes_ids_from_same_title(tmp_path):
    a = brainstorm.add_brainstorm(tmp_path, {"title": "Same idea", "idea": "x"})
    b = brainstorm.add_brainstorm(tmp_path, {"title": "Same idea", "idea": "y"})
    assert a != b
    assert len(brainstorm.read_brainstorms(tmp_path)) == 2


def test_remove_is_idempotent(tmp_path):
    bid = brainstorm.add_brainstorm(tmp_path, {"title": "T", "idea": "i"})
    assert brainstorm.remove_brainstorm(tmp_path, bid) is True
    assert brainstorm.read_brainstorms(tmp_path) == []
    assert brainstorm.remove_brainstorm(tmp_path, bid) is False  # already gone, no error


def test_archived_brainstorm_can_be_discarded_only_by_user(tmp_path):
    bid = brainstorm.add_brainstorm(tmp_path, {"title": "Duplicate", "idea": "x"})
    with pytest.raises(ValueError, match="only an archived Brainstorm"):
        brainstorm.discard_brainstorm(
            tmp_path,
            bid,
            reason="duplicate",
            actor={"type": "user", "id": "reviewer"},
        )

    assert brainstorm.remove_brainstorm(tmp_path, bid)
    with pytest.raises(ValueError, match="requires an explicit user actor"):
        brainstorm.discard_brainstorm(
            tmp_path,
            bid,
            reason="duplicate",
            actor={"type": "agent", "id": "test"},
        )

    item = brainstorm.read_brainstorms(tmp_path, include_archived=True)[0]
    build_interface(ResearchPaths.resolve(workspace=tmp_path, environ={}))
    page = tmp_path / ".research" / "interface" / item["detailPath"]
    assert page.is_file()
    assert brainstorm.discard_brainstorm(
        tmp_path,
        bid,
        reason="content retained in canonical Brainstorm",
        actor={"type": "user", "id": "reviewer"},
    )
    assert brainstorm.read_brainstorms(tmp_path, include_archived=True) == []
    assert page.exists()
    build_interface(ResearchPaths.resolve(workspace=tmp_path, environ={}))
    assert not page.exists()
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    events = EventStore(paths).events()
    assert [event["event_type"] for event in events][-1] == "AggregateRemoved"
    assert any(event["event_type"] == "BrainstormCreated" for event in events)


def test_conversion_binding_identifies_exact_draft_document(tmp_path):
    bid = brainstorm.add_brainstorm(
        tmp_path,
        {"id": "ready-draft", "title": "Ready", "idea": "Bind this document"},
    )
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    draft_package.convert(
        paths,
        brainstorm_id=bid,
        package_id=None,
        actor_id="reviewer",
    )
    current = StateQuery(paths).show("package", bid)["data"]
    assert brainstorm.draft_source_binding(tmp_path, bid) == {
        "id": bid,
        "draft_revision": 1,
        "document_sha256": current["document_note"]["sha256"],
    }


def test_draft_package_context_uses_the_same_governed_document(tmp_path):
    body = _document_body("Agent-visible proposal")
    bid = brainstorm.add_brainstorm(
        tmp_path,
        {
            "id": "bounded-draft",
            "title": "Bounded draft",
            "idea": "Share one canonical proposal with humans and agents.",
            "document_html": body,
        },
    )
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    draft_package.convert(
        paths,
        brainstorm_id=bid,
        package_id=None,
        actor_id="reviewer",
    )
    context = StateQuery(paths).context(bid)["data"]
    assert context["package"]["lifecycle"] == "DRAFT"
    assert context["proposal_document"]["html_fragment"] == body
    assert context["proposal_document"]["note"] == context["package"]["document_note"]
    assert context["execution_authorized"] is False
    assert context["pending_scope"] == []

    compact = StateQuery(paths).compact_context(bid)["data"]
    assert compact["view"] == "compact"
    assert compact["omitted"]["proposal_document_html"] == 1
    assert body not in str(compact)


# --- precondition + readiness ---------------------------------------------

def _project_spec():
    return project_spec()


def _commit_project(workspace, node_id="project/main"):
    node = {"id": node_id, "level": "project", "parents": [], "version": 1,
            "status": "ACTIVE", "spec": _project_spec(), "source": "accepted"}
    paths = ResearchPaths.resolve(workspace=workspace, environ={})
    EventStore(paths).initialize()
    EventStore(paths, fixture_mode=True).commit(
        event_type="AggregateUpserted",
        aggregate_type="project",
        aggregate_id=node_id,
        payload={"record": node},
        actor={"type": "user", "id": "test"},
        idempotency_key=f"seed:{node_id}",
        expected_version=0,
    )


def test_active_project_ids(tmp_path):
    with pytest.raises(UpgradeRequired):
        brainstorm.active_project_ids(tmp_path)
    assert not (tmp_path / ".research").exists()
    _commit_project(tmp_path)
    assert brainstorm.active_project_ids(tmp_path) == ["project/main"]


def test_active_project_context_includes_goal_and_out_of_scope(tmp_path):
    _commit_project(tmp_path)
    context = brainstorm.active_project_context(tmp_path)
    assert context == [{
        "id": "project/main",
        "goal": _project_spec()["goal"],
        "out_of_scope": _project_spec()["out_of_scope"],
    }]


def _good_direction_spec():
    return direction_spec()


def test_direction_ready_true():
    assert brainstorm.direction_ready(_good_direction_spec()) is True


def test_direction_ready_false_missing_field():
    y = {k: v for k, v in _good_direction_spec().items() if k != "success_gate"}
    assert brainstorm.direction_ready(y) is False


def test_direction_ready_false_empty_baselines():
    y = {**_good_direction_spec(), "baselines": []}
    assert brainstorm.direction_ready(y) is False


# --- direction proposal builder -------------------------------------------

def test_build_direction_proposal_valid():
    item = brainstorm.build_direction_proposal(
        "dir/mixup", _good_direction_spec(),
        parent_project_id="project/main", source="brainstorms:bs-1,bs-2",
        source_brainstorms=["bs-1", "bs-2"])
    assert item["level"] == "direction"
    assert item["op"] == "create"
    assert item["gate"] == "USER_CROSS_MODEL_AUDIT"  # direction gate
    assert item["proposed_node"]["parents"] == ["project/main"]
    assert item["proposed_node"]["spec"] == _good_direction_spec()
    assert item["source_brainstorms"] == ["bs-1", "bs-2"]
    assert "id" in item


def test_build_direction_proposal_rejects_reading_in_spec():
    bad = {**_good_direction_spec(), "measured": 0.9}
    with pytest.raises(scope_ssot.RuleViolation):
        brainstorm.build_direction_proposal("dir/x", bad, parent_project_id="project/main",
                                            source="p")


def test_build_direction_proposal_rejects_wrong_level_field():
    bad = {**_good_direction_spec(), "goal": "oops"}  # project field, illegal for direction
    with pytest.raises(scope_ssot.RuleViolation):
        brainstorm.build_direction_proposal("dir/x", bad, parent_project_id="project/main",
                                            source="p")
