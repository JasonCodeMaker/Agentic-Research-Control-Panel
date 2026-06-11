"""The research-analysis rule template reflects registry rows, not legacy hand-edited HTML."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "skills" / "research-analysis" / "templates" / "rule-bullet.html"


def test_rule_template_is_registry_row_payload_not_evidence_link_html():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert '"level":"package"' in text
    assert '"kind":"lesson"' in text
    assert "--target rule" in text
    assert "Evidence:" not in text
    assert "evidence_slug" not in text
