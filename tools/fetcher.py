# ABOUTME: Web content fetcher — cleans HTML to readable text for source evaluation.
# ABOUTME: Falls back to Playwright for JS-rendered/CAPTCHA-gated pages; Wayback for dead URLs.

import httpx
from bs4 import BeautifulSoup

from cache import cached
from tools.wayback import get_archive_url

_MIN_BODY_CHARS = 200
_HEADERS = {"User-Agent": "WikiWriter/1.0"}


def _needs_playwright(status_code: int, body: str) -> bool:
    """Return True if the response suggests JS-rendering or rate-limiting."""
    if status_code in (403, 429):
        return True
    if status_code == 200 and len(body) < _MIN_BODY_CHARS:
        return True
    return False


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


@cached("page_text", ttl=7 * 24 * 3600)
async def fetch_readable(url: str) -> str:
    """
    Fetch URL and return clean readable text, max 8000 chars.
    Detects PDF by content-type and routes to tools/pdf.py.
    Falls back to Playwright if httpx gets blocked (403/429 or short body).
    Falls back to Wayback Machine if httpx fails entirely.
    """
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

    if "application/pdf" in content_type or url.lower().endswith(".pdf"):
        from tools.pdf import extract_pdf_text
        return await extract_pdf_text(url)

    return _html_to_text(html or "")
