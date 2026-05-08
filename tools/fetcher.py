# ABOUTME: Web content fetcher — cleans HTML to readable text for source evaluation.
# ABOUTME: Falls back to Playwright for JS-rendered/CAPTCHA-gated pages; Wayback for dead URLs.

import random
import httpx
from bs4 import BeautifulSoup

from cache import cached
from tools.wayback import get_archive_url

_MIN_BODY_CHARS = 200

# Realistic browser headers to avoid bot detection
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_PLAYWRIGHT_UA = _HEADERS["User-Agent"]

_CAPTCHA_MARKERS = (
    "recaptcha",
    "cf-browser-verification",
    "cloudflare ray id",
    "just a moment",
    "access denied",
    "ddos protection",
    "please wait while we check your browser",
    "are you a human",
)


def _needs_playwright(status_code: int, body: str) -> bool:
    """Return True if the response suggests JS-rendering or rate-limiting."""
    if status_code in (403, 429):
        return True
    if status_code == 200 and len(body) < _MIN_BODY_CHARS:
        return True
    return False


def _has_captcha(html: str) -> bool:
    """Return True if the page appears to be a CAPTCHA or bot-check challenge."""
    lower = html.lower()
    return any(marker in lower for marker in _CAPTCHA_MARKERS)


def _extract_doi(url: str) -> str | None:
    """Return the DOI string from a doi.org or dx.doi.org URL, or None."""
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return None


async def _fetch_via_playwright(url: str) -> str:
    """Render page with headless Chromium; behaves like a real browser to avoid bot detection."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=_PLAYWRIGHT_UA,
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            page = await context.new_page()
            # Block images and fonts — we only need text content
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,eot}",
                lambda route: route.abort(),
            )
            await page.goto(url, timeout=25000, wait_until="domcontentloaded")
            await page.wait_for_timeout(random.uniform(800, 2000))
            content = await page.content()
        finally:
            await browser.close()
    return content


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["nav", "footer", "script", "style", "aside"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)[:8000]


@cached("page_fetch", ttl=7 * 24 * 3600)
async def fetch_raw(url: str) -> tuple[str, str]:
    """Returns (content_type, raw_content). Raises on HTTP error."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=_HEADERS) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "").split(";")[0].strip()
        return content_type, resp.text


@cached("page_text", ttl=7 * 24 * 3600)
async def fetch_readable(url: str) -> str:
    """
    Fetch URL and return clean readable text, max 8000 chars.
    For DOI URLs: checks local paper storage first, then fetches the landing page and
    searches for an open-access PDF via citation metadata, Unpaywall, Semantic Scholar,
    and page link scanning. Falls back to readable text from the landing page.
    For non-DOI URLs: falls back to Playwright if httpx gets blocked (403/429 or short
    body), then to the Wayback Machine if all else fails.
    """
    doi = _extract_doi(url)

    # Fast path: already downloaded this paper locally
    if doi:
        from tools.academic import local_pdf
        if path := local_pdf(doi):
            from tools.pdf import extract_pdf_text
            return await extract_pdf_text(path)

    html = None
    content_type = "text/html"
    fetched_original = False  # True only when we got a response from the original URL

    try:
        ct, raw = await fetch_raw(url)
        content_type = ct
        fetched_original = True
        if _needs_playwright(200, raw):
            html = await _fetch_via_playwright(url)
        else:
            html = raw
    except httpx.HTTPStatusError as e:
        if _needs_playwright(e.response.status_code, ""):
            try:
                html = await _fetch_via_playwright(url)
            except Exception:
                pass
        if html is None:
            archive_url = await get_archive_url(url)
            if archive_url:
                _, html = await fetch_raw(archive_url)
            else:
                raise
    except Exception:
        archive_url = await get_archive_url(url)
        if not archive_url:
            raise
        _, html = await fetch_raw(archive_url)

    # If Playwright returned a CAPTCHA page, try Wayback instead
    if html and _has_captcha(html):
        archive_url = await get_archive_url(url)
        if archive_url:
            _, html = await fetch_raw(archive_url)

    # Check URL extension only when we got a direct response; avoid re-fetching
    # archive-substituted URLs as PDFs when the original returned an error page.
    is_pdf = "application/pdf" in content_type or (fetched_original and url.lower().endswith(".pdf"))
    if is_pdf:
        from tools.pdf import extract_pdf_text
        return await extract_pdf_text(url)

    # For DOI URLs, search the landing page for an open-access PDF
    if doi and html:
        from tools.academic import find_oa_pdf
        if pdf_path := await find_oa_pdf(doi, html, url):
            from tools.pdf import extract_pdf_text
            return await extract_pdf_text(pdf_path)

    return _html_to_text(html or "")
