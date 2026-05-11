# ABOUTME: Web content fetcher — cleans HTML to readable text for source evaluation.
# ABOUTME: Falls back to stealth Playwright for JS-rendered/CAPTCHA-gated pages; Wayback for dead URLs.

import logging
import random
import httpx
from bs4 import BeautifulSoup

from cache import cache, cache_key, record_tool_call
from utils.log import log_tool_call
from tools.wayback import get_archive_url
from tools.academic import _extract_citation_pdf_url

logger = logging.getLogger(__name__)

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
    """Render page with stealth headless Chromium to defeat bot detection."""
    from playwright.async_api import async_playwright
    from playwright_stealth import stealth_async
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=_PLAYWRIGHT_UA,
                viewport={
                    "width": random.randint(1200, 1400),
                    "height": random.randint(700, 900),
                },
                locale="en-US",
            )
            page = await context.new_page()
            await stealth_async(page)
            # Block images and fonts — we only need text content
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,eot}",
                lambda route: route.abort(),
            )
            await page.wait_for_timeout(random.uniform(500, 1500))
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await page.evaluate("window.scrollBy(0, 300)")
            await page.wait_for_timeout(random.uniform(1500, 3000))
            content = await page.content()
        finally:
            await browser.close()
    return content


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["nav", "footer", "script", "style", "aside"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)[:8000]


async def fetch_raw(url: str) -> tuple[str, str]:
    """Returns (content_type, raw_content). Raises on HTTP error."""
    _key = f"page_fetch:{cache_key(url)}"
    if _key in cache:
        return cache[_key]
    async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=_HEADERS) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "").split(";")[0].strip()
        result = content_type, resp.text
    cache.set(_key, result, expire=7 * 24 * 3600)
    return result


async def fetch_readable(url: str) -> str:
    """
    Fetch URL and return clean readable text, max 8000 chars.
    For DOI URLs: checks local paper storage first, then fetches the landing page and
    searches for an open-access PDF via citation metadata, Unpaywall, Semantic Scholar,
    and page link scanning. Falls back to readable text from the landing page.
    For non-DOI URLs: falls back to Playwright if httpx gets blocked (403/429 or short
    body), then to the Wayback Machine if all else fails.
    """
    _key = f"page_text:{cache_key(url)}"
    record_tool_call("fetch")
    log_tool_call("fetch", {"url": url})
    if _key in cache:
        return cache[_key]

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
            logger.warning("httpx blocked/thin response for %s, escalating to stealth Playwright", url)
            html = await _fetch_via_playwright(url)
        else:
            html = raw
    except httpx.HTTPStatusError as e:
        if _needs_playwright(e.response.status_code, ""):
            logger.warning("httpx got %s for %s, escalating to stealth Playwright", e.response.status_code, url)  # noqa: E501
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
        logger.warning("stealth Playwright still blocked by bot-check on %s, trying Wayback", url)
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
            result = await extract_pdf_text(pdf_path)
            cache.set(_key, result, expire=7 * 24 * 3600)
            return result

    # For any other HTML page with a citation_pdf_url meta tag (e.g. arxiv abstract pages),
    # fetch the PDF directly for richer content
    if not doi and html:
        if pdf_url := _extract_citation_pdf_url(html):
            from tools.pdf import extract_pdf_text
            try:
                result = await extract_pdf_text(pdf_url)
                cache.set(_key, result, expire=7 * 24 * 3600)
                return result
            except Exception:
                pass  # Fall through to HTML text extraction

    result = _html_to_text(html or "")
    cache.set(_key, result, expire=7 * 24 * 3600)
    return result
