from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_scope_experiment_renderer_uses_formal_spec_fields():
    js = (ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" /
          "assets" / "research.js").read_text(encoding="utf-8")
    block = js[js.index("function scopeExperimentHtml"):js.index("function objectivePanelHtml")]

    assert "spec.purpose" in block
    assert "spec.config_ref" in block
    assert "spec.control_mode" in block
    assert "spec.gate" in block
    assert "spec.experiment" not in block
    assert "spec.config " not in block
    assert 'class="scope-task"' in block
    assert "<b>Experiment:</b>" in block
    assert "<b>Config:</b>" in block
    assert "spec.objective || spec.hypothesis" not in block


def test_pipeline_timeline_renders_task_thread_chips():
    js = (ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" /
          "assets" / "research.js").read_text(encoding="utf-8")
    block = js[
        js.index("function renderPipelineTimeline"):
        js.index("function implementationDomId")
    ]

    assert "e.purpose" in block
    assert "e.config" in block
    assert "e.controlMode" in block
    assert "e.after" in block
    assert "e.output" in block
    assert "e.gatePredicate || e.gate" in block
    assert "Planned order" in block
    sections = [
        "pipeline-node-sequence",
        "pipeline-node-purpose",
        "pipeline-node-contract",
        "pipeline-operation-fields",
        "pipeline-thread-links",
    ]
    assert [block.index(section) for section in sections] == sorted(
        block.index(section) for section in sections
    )
    assert "pipeline-thread-links" in block
    assert "tracker.html#execution-checklist" in block
    assert "results.html#result-slot-" in block
    assert "implementation.html#implementation-map" in block


def test_plan_template_uses_the_pipeline_as_its_main_content():
    template = (
        ROOT / "skills" / "research-package" / "templates" / "plan.html"
    ).read_text(encoding="utf-8")

    assert 'href="#experiments"' in template
    assert 'data-card="pipeline-timeline"' in template
    assert "Plan invariants" not in template
    assert 'data-card="plan-invariants"' not in template
    assert 'class="plan-legacy-anchor" id="plan-invariants"' in template


def test_implementation_renderer_uses_only_the_checkbox_change_map():
    js = (
        ROOT
        / "skills"
        / "research-dashboard"
        / "assets"
        / "dashboard"
        / "assets"
        / "research.js"
    ).read_text(encoding="utf-8")
    block = js[
        js.index("function implementationDomId"):
        js.index("function trackerTaskHtml")
    ]
    template = (
        ROOT
        / "skills"
        / "research-package"
        / "templates"
        / "implementation.html"
    ).read_text(encoding="utf-8")

    assert "validatingExperiments" in block
    assert "codeLocations" in block
    assert "howItChanges" in block
    assert "verifications" in block
    assert 'type="checkbox"' in block
    assert " disabled" in block
    assert 'data-list="implementation-experiments"' in template
    for removed in (
        "Plan coverage map",
        "Test rule catalog",
        "Pseudo-code",
        "Decision adjudication",
        "hypothesis-restated",
        "change-block",
    ):
        assert removed not in template


def test_results_tables_keep_horizontal_overflow_local():
    css = (
        ROOT
        / "skills"
        / "research-dashboard"
        / "assets"
        / "dashboard"
        / "assets"
        / "research.css"
    ).read_text(encoding="utf-8")

    assert (
        ".result-table-list {\n"
        "  display: grid;\n"
        "  grid-template-columns: minmax(0, 1fr);"
    ) in css
    assert ".result-table {\n  min-width: 0;" in css
    assert (
        ".result-table-scroll {\n"
        "  max-width: 100%;\n"
        "  overflow-x: auto;"
    ) in css


def test_results_renderer_groups_metric_tables_by_experiment():
    js = (
        ROOT
        / "skills"
        / "research-dashboard"
        / "assets"
        / "dashboard"
        / "assets"
        / "research.js"
    ).read_text(encoding="utf-8")
    block = js[
        js.index("function resultTables"):
        js.index("function renderInsightSubblocks")
    ]
    template = (
        ROOT
        / "skills"
        / "research-package"
        / "templates"
        / "results.html"
    ).read_text(encoding="utf-8")

    assert "pkg.experiments" in block
    assert "pkg.resultBlocks" in block
    assert 'type === "main" ? " open" : ""' in block
    assert 'data-result-table-type="' in block
    assert 'table.state || "unverified"' in block
    assert 'value == null || value === "" ? "/"' in block
    assert "Verified CSV" in block
    assert "result-cell-reference" in block
    assert 'target="_blank" rel="noopener noreferrer"' in block
    assert "No hash-bound Result table CSV is attached." in block
    assert "No result tables yet." in block
    assert 'data-list="result-experiments"' in template
    for removed in (
        "Hypothesis (re-stated",
        "Eval contract",
        'data-card="result-gate"',
        'data-card="validity-summary"',
        'data-card="no-change-affirmation"',
        'data-section="agent-zone"',
        "block-insight",
    ):
        assert removed not in template
