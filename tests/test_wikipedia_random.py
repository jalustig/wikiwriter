# ABOUTME: Tests for fetch_random_article — verifies URL construction, title, and description parsing.
# ABOUTME: Patches httpx.get to avoid real network calls.

from unittest.mock import MagicMock, patch

import httpx
import pytest

from tools.wikipedia import fetch_random_article, RateLimitedError


FAKE_API_RESPONSE = {
    "query": {
        "random": [{"title": "Grafana"}],
        "pages": {
            "-1": {
                "title": "Grafana",
                "description": "open-source analytics and visualization platform",
            }
        },
    }
}


def _make_mock_response(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.json.return_value = data
    mock.raise_for_status.return_value = None
    return mock


def test_fetch_random_article_returns_url_title_description():
    with patch("tools.wikipedia.httpx.get", return_value=_make_mock_response(FAKE_API_RESPONSE)):
        url, title, description = fetch_random_article()

    assert url == "https://en.wikipedia.org/wiki/Grafana"
    assert title == "Grafana"
    assert description == "open-source analytics and visualization platform"


def test_fetch_random_article_missing_description_returns_empty_string():
    data = {
        "query": {
            "random": [{"title": "Grafana"}],
            "pages": {"-1": {"title": "Grafana"}},
        }
    }
    with patch("tools.wikipedia.httpx.get", return_value=_make_mock_response(data)):
        url, title, description = fetch_random_article()

    assert title == "Grafana"
    assert description == ""


def test_fetch_random_article_429_raises_rate_limited_with_retry_after():
    mock = MagicMock()
    mock.status_code = 429
    mock.headers = {"Retry-After": "42"}
    mock.raise_for_status.side_effect = httpx.HTTPStatusError(
        "429", request=MagicMock(), response=mock
    )
    with patch("tools.wikipedia.httpx.get", return_value=mock):
        with pytest.raises(RateLimitedError) as exc_info:
            fetch_random_article()
    assert exc_info.value.retry_after == 42


def test_fetch_random_article_429_no_retry_after_header():
    mock = MagicMock()
    mock.status_code = 429
    mock.headers = {}
    mock.raise_for_status.side_effect = httpx.HTTPStatusError(
        "429", request=MagicMock(), response=mock
    )
    with patch("tools.wikipedia.httpx.get", return_value=mock):
        with pytest.raises(RateLimitedError) as exc_info:
            fetch_random_article()
    assert exc_info.value.retry_after is None


def test_fetch_random_article_encodes_spaces_in_url():
    data = {
        "query": {
            "random": [{"title": "Battle of Hastings"}],
            "pages": {"-1": {"title": "Battle of Hastings", "description": "1066 battle"}},
        }
    }
    with patch("tools.wikipedia.httpx.get", return_value=_make_mock_response(data)):
        url, title, description = fetch_random_article()

    assert url == "https://en.wikipedia.org/wiki/Battle_of_Hastings"
    assert title == "Battle of Hastings"
