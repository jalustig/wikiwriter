# ABOUTME: PDF text extraction using pypdf.
# ABOUTME: Handles local file paths and URLs; returns clean text capped at 8000 chars.

import asyncio
import io
import os

import httpx
import pypdf

from cache import cached

_MAX_CHARS = 8000
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _is_local_path(source: str) -> bool:
    """Return True if source is a filesystem path rather than a URL."""
    return not source.startswith(("http://", "https://"))


def _truncate_text(text: str, limit: int = _MAX_CHARS) -> str:
    return text[:limit]


def _extract_from_bytes(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    return "\n\n".join(pages)


@cached("page_text", ttl=7 * 24 * 3600)
async def extract_pdf_text(source: str) -> str:
    """Extract text from a PDF file path or URL. Returns up to 8000 chars."""
    if _is_local_path(source):
        expanded = os.path.expanduser(source)
        loop = asyncio.get_event_loop()
        pdf_bytes = await loop.run_in_executor(None, lambda: open(expanded, "rb").read())
    else:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=30) as client:
            resp = await client.get(source, follow_redirects=True)
            resp.raise_for_status()
            pdf_bytes = resp.content

    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _extract_from_bytes, pdf_bytes)
    return _truncate_text(text)
