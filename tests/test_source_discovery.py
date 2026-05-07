# ABOUTME: Tests for source_discovery URL filtering logic.
# ABOUTME: Verifies Wikipedia/Wikimedia URLs are excluded from candidates.

from workers.source_discovery import _is_allowed_source_url


def test_wikipedia_url_excluded():
    assert _is_allowed_source_url("https://en.wikipedia.org/wiki/Python") is False


def test_wikimedia_url_excluded():
    assert _is_allowed_source_url("https://upload.wikimedia.org/some/file.pdf") is False


def test_valid_url_allowed():
    assert _is_allowed_source_url("https://example.com/valid-source") is True


def test_subdomain_wikipedia_excluded():
    assert _is_allowed_source_url("https://simple.wikipedia.org/wiki/Cat") is False
