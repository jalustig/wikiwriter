# ABOUTME: Web content fetcher — cleans HTML to readable text for source evaluation.
# ABOUTME: Falls back to Playwright for JS-rendered/CAPTCHA-gated pages; Wayback for dead URLs.

import httpx
from bs4 import BeautifulSoup

from cache import cached
from tools.wayback import get_archive_url

_MIN_BODY_CHARS = 200
_HEADERS = {"User-Agent": "WikiWriter/1.0"}

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
    """Render page with headless Chromium and return page text."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(user_agent="WikiWriter/1.0")
            await page.goto(url, timeout=30000, wait_until="networkidle")
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
    async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=_HEADERS) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "").split(";")[0].strip()
        return content_type, resp.text


async def _fetch_oa_version(url: str) -> str | None:
    """Return an open-access URL for the given DOI via Unpaywall, or None."""
    doi = _extract_doi(url)
    if not doi:
        return None
    try:
        async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as client:
            resp = await client.get(
                f"https://api.unpaywall.org/v2/{doi}",
                params={"email": "wikiwriter@wikiwriter.app"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("is_oa"):
                    best = data.get("best_oa_location") or {}
                    return best.get("url_for_pdf") or best.get("url")
    except Exception:
        pass
    return None


@cached("page_text", ttl=7 * 24 * 3600)
async def fetch_readable(url: str) -> str:
    """
    Fetch URL and return clean readable text, max 8000 chars.
    For DOI URLs, tries Unpaywall first for an open-access version.
    Detects PDF by content-type and routes to tools/pdf.py.
    Falls back to Playwright if httpx gets blocked (403/429 or short body).
    If Playwright also returns a CAPTCHA page, falls back to Wayback Machine.
    Falls back to Wayback Machine if httpx fails entirely.
    """
    # For academic DOIs, try to get an open-access version first
    oa_url = await _fetch_oa_version(url)
    if oa_url:
        try:
            return await fetch_readable(oa_url)
        except Exception:
            pass  # fall through to normal fetch of original URL

    html = None
    content_type = "text/html"

    try:
        ct, raw = await fetch_raw(url)
        content_type = ct
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

    if "application/pdf" in content_type or url.lower().endswith(".pdf"):
        from tools.pdf import extract_pdf_text
        return await extract_pdf_text(url)

    return _html_to_text(html or "")
