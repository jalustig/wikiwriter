# ABOUTME: Tests for PDF extraction — file path handling and text extraction.
# ABOUTME: Tests pure logic: path detection, text truncation.

from tools.pdf import _is_local_path, _truncate_text


def test_is_local_path_file_path():
    assert _is_local_path("/Users/jason/doc.pdf") is True


def test_is_local_path_home_expansion():
    assert _is_local_path("~/Documents/file.pdf") is True


def test_is_local_path_http_url():
    assert _is_local_path("https://example.com/file.pdf") is False


def test_is_local_path_relative():
    assert _is_local_path("./relative/path.pdf") is True


def test_truncate_text_within_limit():
    text = "Hello world."
    assert _truncate_text(text, 8000) == text


def test_truncate_text_at_limit():
    text = "x" * 10000
    result = _truncate_text(text, 8000)
    assert len(result) == 8000


def test_truncate_text_exact():
    text = "a" * 8000
    assert _truncate_text(text, 8000) == text


def test_truncate_text_empty():
    assert _truncate_text("", 8000) == ""
