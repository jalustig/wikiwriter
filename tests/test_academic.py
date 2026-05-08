# ABOUTME: Tests for academic.py pure-logic functions — DOI path conversion, metadata extraction, PDF link scanning.
# ABOUTME: No HTTP calls; all tests run against fixture HTML strings.

from tools.academic import (
    doi_to_local_path,
    _extract_citation_pdf_url,
    _candidate_pdf_links,
)


# --- doi_to_local_path ---

def test_doi_to_local_path_simple():
    assert doi_to_local_path("10.1038/nature12373") == "papers/10.1038_nature12373.pdf"


def test_doi_to_local_path_multi_segment():
    assert doi_to_local_path("10.1162/neco.1997.9.8.1735") == "papers/10.1162_neco.1997.9.8.1735.pdf"


def test_doi_to_local_path_url_encoded_slash():
    # DOIs extracted from URLs sometimes carry %2F instead of /
    assert doi_to_local_path("10.1162%2Fneco.1997.9.8.1735") == "papers/10.1162_neco.1997.9.8.1735.pdf"


# --- _extract_citation_pdf_url ---

def test_extract_citation_pdf_url_name_attr():
    html = '<html><head><meta name="citation_pdf_url" content="https://example.com/paper.pdf"></head></html>'
    assert _extract_citation_pdf_url(html) == "https://example.com/paper.pdf"


def test_extract_citation_pdf_url_property_attr():
    html = '<html><head><meta property="citation_pdf_url" content="https://example.com/paper.pdf"></head></html>'
    assert _extract_citation_pdf_url(html) == "https://example.com/paper.pdf"


def test_extract_citation_pdf_url_missing():
    html = "<html><head><title>Paywalled Paper</title></head><body>Subscribe to read.</body></html>"
    assert _extract_citation_pdf_url(html) is None


def test_extract_citation_pdf_url_empty_content():
    html = '<html><head><meta name="citation_pdf_url" content=""></head></html>'
    assert _extract_citation_pdf_url(html) is None


# --- _candidate_pdf_links ---

def test_candidate_pdf_links_direct_href():
    html = '<html><body><a href="https://example.com/paper.pdf">Download</a></body></html>'
    assert "https://example.com/paper.pdf" in _candidate_pdf_links(html, "https://example.com")


def test_candidate_pdf_links_relative_href():
    html = '<html><body><a href="/articles/paper.pdf">PDF</a></body></html>'
    result = _candidate_pdf_links(html, "https://journal.com")
    assert "https://journal.com/articles/paper.pdf" in result


def test_candidate_pdf_links_path_contains_pdf():
    html = '<html><body><a href="https://journal.com/content/pdf/10.1038_article">Full text</a></body></html>'
    result = _candidate_pdf_links(html, "https://journal.com")
    assert "https://journal.com/content/pdf/10.1038_article" in result


def test_candidate_pdf_links_ignores_non_pdf():
    html = '<html><body><a href="https://example.com/page.html">Read online</a></body></html>'
    assert _candidate_pdf_links(html, "https://example.com") == []


def test_candidate_pdf_links_deduplicates():
    html = """<html><body>
        <a href="https://example.com/paper.pdf">Download PDF</a>
        <a href="https://example.com/paper.pdf">Get PDF</a>
    </body></html>"""
    result = _candidate_pdf_links(html, "https://example.com")
    assert result.count("https://example.com/paper.pdf") == 1


def test_candidate_pdf_links_skips_images():
    # .pdf check should not match image URLs that happen to contain pdf text
    html = '<html><body><a href="https://example.com/cover.png">Cover</a></body></html>'
    assert _candidate_pdf_links(html, "https://example.com") == []
