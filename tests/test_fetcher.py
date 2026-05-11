# ABOUTME: Tests for fetcher pure logic — Playwright trigger condition, CAPTCHA detection, DOI extraction.
# ABOUTME: Tests heuristics without actual HTTP calls.

from tools.fetcher import _needs_playwright, _has_captcha, _extract_doi, _extract_citation_pdf_url


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


def test_has_captcha_recaptcha():
    assert _has_captcha("<html><body>Please complete the reCAPTCHA</body></html>") is True


def test_has_captcha_cloudflare():
    assert _has_captcha("<html>Checking your browser... Cloudflare Ray ID: abc</html>") is True


def test_has_captcha_just_a_moment():
    assert _has_captcha("<html>Just a moment...</html>") is True


def test_has_captcha_normal_page():
    assert _has_captcha("<html><body><p>This is a normal article about economics.</p></body></html>") is False


def test_has_captcha_case_insensitive():
    assert _has_captcha("<html>RECAPTCHA challenge required</html>") is True


def test_extract_doi_doi_org():
    assert _extract_doi("https://doi.org/10.1038/nature12373") == "10.1038/nature12373"


def test_extract_doi_dx_doi_org():
    assert _extract_doi("https://dx.doi.org/10.1093/brain/awv001") == "10.1093/brain/awv001"


def test_extract_doi_no_doi():
    assert _extract_doi("https://www.nature.com/articles/something") is None


def test_extract_doi_pubmed():
    assert _extract_doi("https://pubmed.ncbi.nlm.nih.gov/12345678/") is None


def test_extract_doi_with_path_segment():
    assert _extract_doi("https://doi.org/10.1126/science.1258351") == "10.1126/science.1258351"


def test_extract_citation_pdf_url_name_attr():
    html = '<html><head><meta name="citation_pdf_url" content="https://arxiv.org/pdf/1234.5678"></head></html>'
    assert _extract_citation_pdf_url(html) == "https://arxiv.org/pdf/1234.5678"


def test_extract_citation_pdf_url_property_attr():
    html = '<html><head><meta property="citation_pdf_url" content="https://arxiv.org/pdf/1234.5678"></head></html>'
    assert _extract_citation_pdf_url(html) == "https://arxiv.org/pdf/1234.5678"


def test_extract_citation_pdf_url_missing():
    html = "<html><head><title>No PDF here</title></head><body>Text only.</body></html>"
    assert _extract_citation_pdf_url(html) is None


def test_extract_citation_pdf_url_empty_content():
    html = '<html><head><meta name="citation_pdf_url" content=""></head></html>'
    assert _extract_citation_pdf_url(html) is None
