import json

from lib.interface import parity
from lib.interface.parity import (
    DEFAULT_CONTRACT,
    HTML_FILES,
    ParityResult,
    SCREENSHOT_FLAGS,
    SCREENSHOT_POLICY,
    VISUAL_PAGES,
    cached_check_contract,
    check_contract,
    clear_contract_cache,
    legacy_dom_parity_report,
)


def test_frozen_dom_and_css_contract():
    result = check_contract(include_visual=False)
    assert result.dom_files == 12
    assert result.css_files == 2


def test_frozen_visual_contract():
    result = check_contract(include_visual=True)
    assert result.visual_pages == 12


def test_contract_covers_every_frozen_page_and_exact_render_environment():
    contract = json.loads(DEFAULT_CONTRACT.read_text(encoding="utf-8"))

    assert contract["schema_version"] == 2
    assert set(contract["dom"]) == set(HTML_FILES)
    assert set(contract["visual"]) == set(VISUAL_PAGES)
    assert contract["screenshot_policy"] == SCREENSHOT_POLICY
    assert contract["screenshot_flags"] == list(SCREENSHOT_FLAGS)
    assert contract["browser_version"]
    assert contract["fonts"]["sha256"]
    assert contract["runtime"]["sha256"]
    assert contract["render_environment_sha256"]


def test_legacy_dom_parity_allows_only_migrated_paths_and_footer_help(tmp_path):
    legacy = tmp_path / "research_html"
    projected = tmp_path / ".research" / "interface"
    legacy.mkdir(parents=True)
    projected.mkdir(parents=True)
    (legacy / "index.html").write_text(
        "<html><body><main><a href=\"/research_html/live.html\">Live</a></main>"
        "<footer class=\"footer-note\">Run python research_html/scripts/"
        "serve_dashboard.py and inspect outputs/pkg.</footer></body></html>",
        encoding="utf-8",
    )
    (projected / "index.html").write_text(
        "<html><body><main><a href=\"/.research/interface/live.html\">Live</a></main>"
        "<footer class=\"footer-note\">Run python -m lib.interface.serve and "
        "inspect .research/experiments/pkg.</footer></body></html>",
        encoding="utf-8",
    )

    report = legacy_dom_parity_report(legacy, projected)

    assert report["ok"] is True
    assert report["checked"] == ["index.html"]


def test_legacy_dom_parity_rejects_structural_or_visible_copy_drift(tmp_path):
    legacy = tmp_path / "research_html"
    projected = tmp_path / ".research" / "interface"
    legacy.mkdir(parents=True)
    projected.mkdir(parents=True)
    (legacy / "index.html").write_text(
        "<html><body><main class=\"shell\"><h1>Research</h1></main></body></html>",
        encoding="utf-8",
    )
    (projected / "index.html").write_text(
        "<html><body><main class=\"redesign\"><h1>Dashboard</h1></main></body></html>",
        encoding="utf-8",
    )

    report = legacy_dom_parity_report(legacy, projected)

    assert report["ok"] is False
    assert report["drift"][0]["path"] == "index.html"


def test_cached_contract_check_does_not_repeat_the_expensive_gate(monkeypatch):
    calls = 0

    def fake_check(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return ParityResult(
            browser_major=150,
            browser_version="Chromium 150.0.0.0",
            dom_files=12,
            css_files=2,
            visual_pages=12,
            font_fingerprint="font",
            runtime_fingerprint="runtime",
        )

    clear_contract_cache()
    monkeypatch.setattr(parity, "check_contract", fake_check)

    first = cached_check_contract(include_visual=False)
    second = cached_check_contract(include_visual=False)

    assert first == second
    assert calls == 1
    clear_contract_cache()
