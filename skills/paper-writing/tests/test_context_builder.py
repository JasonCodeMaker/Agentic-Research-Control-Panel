"""Stage 1 — build_paper_context assembles typed context, never invents evidence."""

import textwrap

import common
import build_paper_context as bpc


def _make_project(tmp_root, paper_yaml, results_files=None):
    home = common.ensure_project_skeleton("demo", root=tmp_root)
    common.write_text(home / "paper.yaml", textwrap.dedent(paper_yaml))
    for rel, body in (results_files or {}).items():
        common.write_text(home / rel, body)
    return home


FULL_YAML = """\
paper:
  id: demo
  title: "Event-Centric Video Retrieval"
  target_venue: NeurIPS
  paper_type: method
claims:
  identity: "EventRetr reframes retrieval as event matching."
  main:
    - id: C1
      text: "EventRetr improves Recall@5 by 13x on MSR-VTT."
      evidence: inputs/results/main_table.md
      value: "47.3"
      status: supported
      wording: strong
  secondary: []
  limitations:
    - "Gains shrink on short clips."
evidence:
  results: [inputs/results/main_table.md]
  metrics:
    - name: "Recall@5"
      value: "47.3"
      source: inputs/results/main_table.md
  baselines: [CLIP, X-CLIP]
  ablations: []
  datasets: [MSR-VTT]
  runtime_provenance: "8xA100, seed 0"
figures:
  existing:
    - {name: pipeline, kind: non-data}
  missing:
    - {name: ablation_curve, kind: data}
terminology:
  method_name: EventRetr
  module_names: [EventEncoder]
  metric_names: ["Recall@5"]
  dataset_names: ["MSR-VTT"]
  forbidden_synonyms: [model, network]
  citation_keys: [vaswani2017]
  latex_labels: ["fig:pipeline"]
"""


def test_builds_three_context_files(tmp_root):
    _make_project(tmp_root, FULL_YAML,
                  {"inputs/results/main_table.md": "Recall@5 = 47.3 on MSR-VTT [vaswani2017]"})
    bpc.build_context("demo", root=tmp_root)
    ctx = tmp_root / "projects" / "demo" / "context"
    assert (ctx / "paper_context.md").is_file()
    assert (ctx / "claim_evidence_map.md").is_file()
    assert (ctx / "figure_table_inventory.md").is_file()


def test_preserves_facts_verbatim(tmp_root):
    _make_project(tmp_root, FULL_YAML,
                  {"inputs/results/main_table.md": "Recall@5 = 47.3 on MSR-VTT [vaswani2017]"})
    bpc.build_context("demo", root=tmp_root)
    text = common.read_text(tmp_root / "projects" / "demo" / "context" / "paper_context.md")
    for token in ("Recall@5", "47.3", "MSR-VTT", "EventRetr", "vaswani2017"):
        assert token in text


def test_refuses_to_mark_missing_evidence_as_supported(tmp_root):
    # Claim says supported but its evidence file does not exist.
    _make_project(tmp_root, FULL_YAML, results_files={})  # no main_table.md written
    result = bpc.build_context("demo", root=tmp_root)
    cem = common.read_text(tmp_root / "projects" / "demo" / "context" / "claim_evidence_map.md")
    assert "MISSING" in cem
    assert result["claim_status"]["C1"] == "MISSING"
    # the originally-declared 'SUPPORTED' must not survive.
    assert "SUPPORTED" not in cem.split("Status")[0] or result["claim_status"]["C1"] != "SUPPORTED"


def test_partial_when_declared_value_absent(tmp_root):
    _make_project(tmp_root, FULL_YAML,
                  {"inputs/results/main_table.md": "Recall@5 reported but no number here"})
    result = bpc.build_context("demo", root=tmp_root)
    assert result["claim_status"]["C1"] == "PARTIAL"


def test_gap_report_for_missing_venue_baselines_results(tmp_root):
    sparse = """\
    paper:
      id: demo
      title: "Untitled"
      target_venue: null
      paper_type: method
    claims:
      identity: "TBD"
      main: []
      secondary: []
      limitations: []
    evidence:
      results: []
      metrics: []
      baselines: []
      ablations: []
      datasets: []
      runtime_provenance: ""
    figures: {existing: [], missing: []}
    terminology:
      method_name: TBD
      module_names: []
      metric_names: []
      dataset_names: []
      forbidden_synonyms: []
      citation_keys: []
    """
    _make_project(tmp_root, sparse)
    result = bpc.build_context("demo", root=tmp_root)
    gap = common.read_text(tmp_root / "projects" / "demo" / "context" / "gap_report.md")
    assert "venue" in gap.lower()
    assert "baseline" in gap.lower()
    assert "result" in gap.lower()
    assert result["gaps"]
