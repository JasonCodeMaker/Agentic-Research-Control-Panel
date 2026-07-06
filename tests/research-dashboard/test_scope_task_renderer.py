from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_scope_task_renderer_uses_task_spec_fields():
    js = (ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" /
          "assets" / "research.js").read_text(encoding="utf-8")
    block = js[js.index("function scopeTaskHtml"):js.index("function objectivePanelHtml")]

    assert "spec.experiment" in block
    assert "spec.config" in block
    assert "spec.control_mode" in block
    assert "spec.gate" in block
    assert "spec.objective || spec.hypothesis" not in block


def test_pipeline_timeline_renders_task_thread_chips():
    js = (ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" /
          "assets" / "research.js").read_text(encoding="utf-8")
    block = js[js.index("function renderPipelineTimeline"):js.index("function renderImplementationPhaseStrip")]

    assert "pipeline-thread-links" in block
    assert "tracker.html#todo" in block
    assert "results.html#result-slot-" in block
    assert "implementation.html#changes" in block
