"""Package contract docs describe the current analysis rule ownership model."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "skills" / "research-package" / "references" / "package-contract.md"
AGENT_CONTEXT_TEMPLATE = ROOT / "skills" / "research-package" / "templates" / "_agent" / "context.html"


def test_analysis_rules_contract_names_registry_paint_not_legacy_evidence_links():
    text = CONTRACT.read_text(encoding="utf-8")
    assert "data/rules.js" in text
    assert "kind=lesson" in text
    assert "Evidence:" not in text
    assert "one `Evidence:" not in text


def test_agent_context_template_loads_context_pack_before_stage_pages():
    text = AGENT_CONTEXT_TEMPLATE.read_text(encoding="utf-8")
    assert "outputs/$package_id/context_pack.md" in text
    assert "failed methods" in text
    assert "adopted wins" in text
    assert "active rules" in text
    for retired in ("launch / live", "next-action", "launch.html", "live.html", "next-action.html"):
        assert retired not in text
