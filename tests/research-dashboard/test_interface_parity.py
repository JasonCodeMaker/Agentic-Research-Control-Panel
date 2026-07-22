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
)


def test_frozen_dom_and_css_contract():
    result = check_contract(include_visual=False)
    assert result.dom_files == 13
    assert result.css_files == 3


def test_frozen_visual_contract():
    result = check_contract(include_visual=True)
    assert result.visual_pages == 13


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
