# ABOUTME: Tests for fetcher pure logic — Playwright trigger condition.
# ABOUTME: Tests _needs_playwright() heuristic without actual HTTP calls.

from tools.fetcher import _needs_playwright


def test_needs_playwright_403():
    assert _needs_playwright(403, "some content") is True


def test_needs_playwright_429():
    assert _needs_playwright(429, "some content") is True


def test_needs_playwright_200_short_body():
    # Body shorter than 200 chars suggests JS-rendered or blocked page
    assert _needs_playwright(200, "x" * 150) is True


def test_needs_playwright_200_normal_body():
    assert _needs_playwright(200, "x" * 500) is False


def test_needs_playwright_404():
    # 404 is a real not-found, not a JS-gating issue
    assert _needs_playwright(404, "") is False


def test_needs_playwright_500():
    assert _needs_playwright(500, "") is False
