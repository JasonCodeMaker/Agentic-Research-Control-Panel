import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from lib.research_state import EventStore, ResearchPaths  # noqa: E402

BUNDLE = REPO / "skills/research-dashboard/assets/dashboard"
ASSETS = BUNDLE / "assets"


def _node(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["node", "-e", script], capture_output=True, text=True)


def _require_with_dom_stubs(js_path: Path) -> subprocess.CompletedProcess:
    # Minimal browser stubs so a renderer IIFE can execute at load under node.
    script = (
        "global.window = {};"
        "global.navigator = {};"
        "global.document = {"
        "  addEventListener: function(){},"
        "  readyState: 'complete',"
        "  querySelectorAll: function(){ return []; },"
        "  querySelector: function(){ return null; },"
        "  body: { getAttribute: function(){ return null; } }"
        "};"
        # A module may eagerly render at load (readyState !== 'loading'); that render
        # throws under the headless stub. Registration happens first, so tolerate it.
        f"try {{ require({str(js_path).__repr__()}); }} catch (e) {{}}"
        "if (!Array.isArray(window.__researchRenderers)) { console.error('no registry'); process.exit(1); }"
        "if (typeof window.__researchRenderers[0] !== 'function') { console.error('not a fn'); process.exit(2); }"
        "process.exit(0);"
    )
    return _node(script)


def test_research_js_registers_a_renderer():
    result = _require_with_dom_stubs(ASSETS / "research.js")
    assert result.returncode == 0, result.stderr


def test_scope_inspector_registers_refresh():
    src = (ASSETS / "scope-inspector.js").read_text(encoding="utf-8")
    assert "__researchRenderers" in src, "scope-inspector must register on the shared registry"
    assert "push(refresh)" in src, "scope-inspector must register its refresh entrypoint"


def test_scope_inspector_node_check():
    result = subprocess.run(
        ["node", "--check", str(ASSETS / "scope-inspector.js")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def _require_livedata(assertions: str) -> subprocess.CompletedProcess:
    path = ASSETS / "live-data.js"
    script = f"const m = require({str(path).__repr__()});" + assertions
    return _node(script)


def test_live_data_pure_helpers_exist_and_hash_is_stable():
    out = _require_livedata(
        "if (typeof m.hashText !== 'function') process.exit(1);"
        "if (typeof m.dataSourceUrls !== 'function') process.exit(2);"
        "if (m.hashText('alpha') !== m.hashText('alpha')) process.exit(3);"
        "if (m.hashText('alpha') === m.hashText('beta')) process.exit(4);"
        "process.exit(0);"
    )
    assert out.returncode == 0, out.stderr


def test_live_data_filters_only_data_sources():
    out = _require_livedata(
        "const got = m.dataSourceUrls(["
        "'data/research-packages.js','assets/research.js',"
        "'../../data/schema.js','data/x.js?_=1','mydata/x.js'"
        "]);"
        "const want = ['data/research-packages.js','../../data/schema.js','data/x.js?_=1'];"
        "if (JSON.stringify(got) !== JSON.stringify(want)) { console.error(JSON.stringify(got)); process.exit(1); }"
        "process.exit(0);"
    )
    assert out.returncode == 0, out.stderr


def test_live_data_first_seen_fetch_evaluates_data_file():
    out = _require_livedata(
        "const state = {};"
        "let evalCount = 0;"
        "const changed = m.applyFetchedData("
        "  'http://127.0.0.1:8904/data/scope-projection.js',"
        "  'window.RESEARCH_SCOPE_PROJECTION = {\"project/x\": {}};',"
        "  state,"
        "  function(text) { evalCount += 1; global.window = global.window || {}; (0, eval)(text); }"
        ");"
        "if (changed !== true) { console.error('not changed'); process.exit(1); }"
        "if (evalCount !== 1) { console.error('not evaled'); process.exit(2); }"
        "if (!global.window.RESEARCH_SCOPE_PROJECTION['project/x']) { console.error('not assigned'); process.exit(3); }"
        "const unchanged = m.applyFetchedData('http://127.0.0.1:8904/data/scope-projection.js',"
        "  'window.RESEARCH_SCOPE_PROJECTION = {\"project/x\": {}};', state, function() { evalCount += 1; });"
        "if (unchanged !== false || evalCount !== 1) { console.error('unchanged path failed'); process.exit(4); }"
        "process.exit(0);"
    )
    assert out.returncode == 0, out.stderr


def test_live_data_node_check():
    result = subprocess.run(
        ["node", "--check", str(ASSETS / "live-data.js")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_live_data_browser_bootstrap_is_guarded():
    # Requiring under node (no document) must NOT start polling or throw.
    out = _require_livedata("process.exit(0);")
    assert out.returncode == 0, out.stderr


# (surface relative path, renderer script substring that must precede live-data.js, live-data src)
WIRED_SURFACES = [
    ("index.html", "assets/research.js", "assets/live-data.js"),
    ("learnings.html", "assets/research.js", "assets/live-data.js"),
    ("module.html", "assets/research.js", "assets/live-data.js"),
    ("scope.html", "assets/scope-inspector.js", "assets/live-data.js"),
    ("categories/in-progress/index.html", "../../assets/research.js", "../../assets/live-data.js"),
    ("categories/brainstorm/index.html", "../../assets/research.js", "../../assets/live-data.js"),
    ("categories/success/index.html", "../../assets/research.js", "../../assets/live-data.js"),
    ("categories/fail/index.html", "../../assets/research.js", "../../assets/live-data.js"),
]


@pytest.mark.parametrize("surface,renderer,livedata", WIRED_SURFACES)
def test_surface_includes_live_data_after_renderer(surface, renderer, livedata):
    html = (BUNDLE / surface).read_text(encoding="utf-8")
    assert livedata in html, f"{surface} missing live-data.js include"
    assert renderer in html, f"{surface} missing renderer script {renderer}"
    assert html.index(livedata) > html.index(renderer), (
        f"{surface}: live-data.js must come after the renderer script"
    )


def test_live_html_not_wired():
    # live.html has its own poller and must stay the reference implementation.
    html = (BUNDLE / "live.html").read_text(encoding="utf-8")
    assert "live-data.js" not in html


def test_scaffold_emits_live_data(tmp_path):
    root = tmp_path / ".research" / "interface"
    EventStore(ResearchPaths.resolve(workspace=tmp_path)).initialize()
    script = REPO / "skills/research-dashboard/scripts/ensure_dashboard.py"
    result = subprocess.run(
        [sys.executable, str(script), "--workspace", str(tmp_path), "build"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert (root / "assets/live-data.js").exists(), "live-data.js was not scaffolded"
    index_html = (root / "index.html").read_text(encoding="utf-8")
    assert "assets/live-data.js" in index_html


def _compact_markdown_commands(text: str) -> str:
    return " ".join(text.replace("\\\n", " ").split())


def test_skill_documents_projection_refresh_and_ssh_viewer():
    skill = (REPO / "skills/research-dashboard/SKILL.md").read_text(encoding="utf-8")
    assert "assets/live-data.js" in skill
    assert "python3 -m lib.interface.serve" in skill
    assert "ssh -L" in skill, "SKILL.md must document the SSH port-forward access path"


def test_skill_documents_build_serve_ensure_and_status_commands():
    skill = (REPO / "skills/research-dashboard/SKILL.md").read_text(encoding="utf-8")
    compact = _compact_markdown_commands(skill)
    assert (
        "python3 skills/research-dashboard/scripts/ensure_dashboard.py "
        "--workspace . build"
    ) in compact
    for command in ("serve", "ensure", "status", "stop"):
        assert (
            f"python3 -m lib.interface.serve --workspace . {command}"
        ) in compact
    assert "XDG_RUNTIME_DIR" in skill
    assert "research-init" in skill
    assert "python3 -m lib.interface.parity check" in skill


def test_skill_keeps_only_the_current_dashboard_reference():
    references = REPO / "skills/research-dashboard/references"
    assert sorted(path.name for path in references.glob("*.md")) == [
        "dashboard-contract.md"
    ]
