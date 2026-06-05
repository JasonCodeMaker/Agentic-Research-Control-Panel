from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_scope_task_renderer_uses_task_yardstick_fields():
    js = (ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" /
          "assets" / "research.js").read_text(encoding="utf-8")
    block = js[js.index("function scopeTaskHtml"):js.index("function protocolHeroHtml")]

    assert "yard.experiment" in block
    assert "yard.config_ref" in block
    assert "yard.autonomy_level" in block
    assert "yard.gate_predicate" in block
    assert "yard.objective || yard.hypothesis" not in block
