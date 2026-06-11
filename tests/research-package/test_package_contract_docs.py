"""Package contract docs describe the current analysis rule ownership model."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "skills" / "research-package" / "references" / "package-contract.md"


def test_analysis_rules_contract_names_registry_paint_not_legacy_evidence_links():
    text = CONTRACT.read_text(encoding="utf-8")
    assert "data/rules.js" in text
    assert "kind=lesson" in text
    assert "Evidence:" not in text
    assert "one `Evidence:" not in text
