# ABOUTME: Web content fetcher — cleans HTML to readable text for source evaluation.
# ABOUTME: Playwright fallback stub; full implementation in M8.

import httpx
from bs4 import BeautifulSoup

from cache import cached
from tools.wayback import get_archive_url


@cached("page_fetch", ttl=7 * 24 * 3600)
async def fetch_raw(url: str) -> tuple[str, str]:
    """Returns (content_type, raw_content). Raises on HTTP error."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(url, headers={"User-Agent": "WikiWriter/1.0"})
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "").split(";")[0].strip()
        return content_type, resp.text


@cached("page_text", ttl=7 * 24 * 3600)
async def fetch_readable(url: str) -> str:
    """
    Fetch URL and return clean readable text, max 8000 chars.
    Detects PDF by content-type and routes to tools/pdf.py (stub for now).
    Falls back to Wayback Machine if httpx fails.
    """
    try:
        content_type, raw = await fetch_raw(url)
    except Exception:
        archive_url = await get_archive_url(url)
        if not archive_url:
            raise
        content_type, raw = await fetch_raw(archive_url)

    if "application/pdf" in content_type:
        from tools.pdf import extract_pdf_text
        try:
            return await extract_pdf_text(url)
        except NotImplementedError:
            return ""

    soup = BeautifulSoup(raw, "lxml")
    for tag in soup.find_all(["nav", "footer", "script", "style", "aside"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    return text[:8000]
