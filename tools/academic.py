# ABOUTME: Open-access PDF discovery for academic papers identified by DOI.
# ABOUTME: Checks local storage first, then citation metadata, Unpaywall, Semantic Scholar, and page links.

# Future: Google Scholar scraping via Playwright (search title, follow [PDF] links) would be a
# high-yield next step for papers not covered by Unpaywall or Semantic Scholar. It requires
# careful rate-limiting and a rotating user-agent to avoid triggering bot detection, and
# should only be attempted after all structured API sources are exhausted.

import os
from urllib.parse import urljoin, unquote

import httpx
from bs4 import BeautifulSoup

from cache import record_tool_call

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PAPERS_DIR = os.getenv("PAPERS_DIR", "papers")


def doi_to_local_path(doi: str) -> str:
    """Return the local file path for a given DOI."""
    safe = unquote(doi).replace("/", "_")
    return os.path.join(PAPERS_DIR, f"{safe}.pdf")


def local_pdf(doi: str) -> str | None:
    """Return local path if we already have this paper downloaded, else None."""
    path = doi_to_local_path(doi)
    return path if os.path.exists(path) else None


def _save_pdf(doi: str, pdf_bytes: bytes) -> str:
    """Write PDF bytes to papers/{doi}.pdf and return the path."""
    os.makedirs(PAPERS_DIR, exist_ok=True)
    path = doi_to_local_path(doi)
    with open(path, "wb") as f:
        f.write(pdf_bytes)
    return path


def _extract_citation_pdf_url(html: str) -> str | None:
    """Return the citation_pdf_url meta tag value if present, else None."""
    soup = BeautifulSoup(html, "lxml")
    tag = (
        soup.find("meta", attrs={"name": "citation_pdf_url"})
        or soup.find("meta", attrs={"property": "citation_pdf_url"})
    )
    if tag:
        url = tag.get("content", "").strip()
        return url or None
    return None


def _candidate_pdf_links(html: str, base_url: str) -> list[str]:
    """
    Return deduplicated candidate PDF URLs found in page links.
    Matches direct .pdf hrefs and publisher path patterns like /pdf/ or /doi/pdf/.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    candidates: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        abs_url = urljoin(base_url, href)
        lower = abs_url.lower()
        if abs_url in seen:
            continue
        if abs_url.split("?")[0].endswith(".pdf") or "/pdf/" in lower:
            seen.add(abs_url)
            candidates.append(abs_url)
    return candidates


async def _fetch_pdf_bytes(url: str, client: httpx.AsyncClient) -> bytes | None:
    """
    Return PDF bytes if the URL serves a PDF, else None.
    HEAD-checks content-type first to avoid downloading non-PDF responses.
    Falls through to GET if HEAD is not supported.
    """
    try:
        head = await client.head(url, follow_redirects=True, timeout=10)
        ct = head.headers.get("content-type", "").lower()
        if head.status_code == 200 and ct and "pdf" not in ct:
            return None
    except Exception:
        pass  # HEAD not supported — attempt GET anyway

    try:
        resp = await client.get(url, follow_redirects=True, timeout=30)
        if resp.status_code != 200:
            return None
        if "pdf" not in resp.headers.get("content-type", "").lower():
            return None
        return resp.content
    except Exception:
        return None


async def _unpaywall_pdf_url(doi: str, client: httpx.AsyncClient) -> str | None:
    """Return an OA PDF URL from Unpaywall for the given DOI, or None."""
    try:
        resp = await client.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": "wikiwriter@wikiwriter.app"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("is_oa"):
                best = data.get("best_oa_location") or {}
                return best.get("url_for_pdf") or best.get("url")
    except Exception:
        pass
    return None


async def _semantic_scholar_pdf_url(doi: str, client: httpx.AsyncClient) -> str | None:
    """Return an OA PDF URL from Semantic Scholar for the given DOI, or None."""
    try:
        resp = await client.get(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
            params={"fields": "openAccessPdf"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            oa = data.get("openAccessPdf")
            if oa:
                return oa.get("url")
    except Exception:
        pass
    return None


async def find_oa_pdf(doi: str, landing_html: str, base_url: str) -> str | None:
    """
    Find and download an open-access PDF for the given DOI.
    Returns the local file path on success, or None if no OA version is found.

    Lookup order:
      1. Local disk (papers/{doi}.pdf) — free, instant
      2. citation_pdf_url meta tag — publisher-provided direct link, no extra HTTP
      3. Unpaywall — structured OA registry, highest reliability
      4. Semantic Scholar — good coverage of CS/ML/biomedical
      5. Page link scan — catches /pdf/ paths and direct .pdf hrefs
    """
    record_tool_call("academic")
    # 1. Already downloaded
    if path := local_pdf(doi):
        return path

    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as client:
        # 2. citation_pdf_url meta tag
        if url := _extract_citation_pdf_url(landing_html):
            if pdf_bytes := await _fetch_pdf_bytes(url, client):
                return _save_pdf(doi, pdf_bytes)

        # 3. Unpaywall
        if url := await _unpaywall_pdf_url(doi, client):
            if pdf_bytes := await _fetch_pdf_bytes(url, client):
                return _save_pdf(doi, pdf_bytes)

        # 4. Semantic Scholar
        if url := await _semantic_scholar_pdf_url(doi, client):
            if pdf_bytes := await _fetch_pdf_bytes(url, client):
                return _save_pdf(doi, pdf_bytes)

        # 5. Page link scan
        for url in _candidate_pdf_links(landing_html, base_url):
            if pdf_bytes := await _fetch_pdf_bytes(url, client):
                return _save_pdf(doi, pdf_bytes)

    return None
