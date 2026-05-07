# ABOUTME: MediaWiki API client for fetching article content, edit history, and talk pages.
# ABOUTME: Uses wikipedia-api for sections/text and prop=extlinks for comprehensive citation coverage.

import re
import asyncio
import httpx
import mwparserfromhell
import wikipediaapi
from urllib.parse import unquote

from cache import cache_key, cache
from models import WikiArticle, Citation

MEDIAWIKI_API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "WikiWriter/1.0"}

_wiki = wikipediaapi.Wikipedia(language="en", user_agent="WikiWriter/1.0")


def _title_from_url(url: str) -> str:
    """Extract article title from a Wikipedia URL or return the input as-is."""
    match = re.match(r"https?://en\.wikipedia\.org/wiki/(.+)", url)
    if match:
        return unquote(match.group(1)).replace("_", " ")
    return url


def _sections_from_page(page: wikipediaapi.WikipediaPage) -> tuple[list[str], dict[str, str]]:
    """Build section list from wikipedia-api page (returns clean plain text, not wikitext)."""
    section_names: list[str] = ["Lead"]
    section_texts: dict[str, str] = {"Lead": page.summary}

    def _walk(sections: list) -> None:
        for s in sections:
            name = s.title.strip()
            unique_name = name
            suffix = 2
            while unique_name in section_texts:
                unique_name = f"{name} ({suffix})"
                suffix += 1
            section_names.append(unique_name)
            section_texts[unique_name] = s.text
            _walk(s.sections)

    _walk(page.sections)
    return section_names, section_texts


def _parse_sections_from_wikitext(wikitext: str) -> tuple[list[str], dict[str, str]]:
    """Fallback: parse wikitext into sections using mwparserfromhell."""
    parsed = mwparserfromhell.parse(wikitext)
    sections = parsed.get_sections(include_lead=True, flat=True)
    section_names: list[str] = []
    section_texts: dict[str, str] = {}
    for section in sections:
        headings = section.filter_headings()
        name = headings[0].title.strip() if headings else "Lead"
        unique_name = name
        suffix = 2
        while unique_name in section_texts:
            unique_name = f"{name} ({suffix})"
            suffix += 1
        section_names.append(unique_name)
        section_texts[unique_name] = str(section)
    return section_names, section_texts


def _build_citations(extlinks: list[str], wikitext: str) -> list[Citation]:
    """
    Build Citation objects from all external links found by prop=extlinks.
    Catches all citation styles ({{cite}}, {{sfn}}, bare URLs, etc.).
    Finds surrounding claim context by locating the URL in the raw wikitext.
    """
    citations: list[Citation] = []
    for i, url in enumerate(extlinks):
        pos = wikitext.find(url)
        if pos >= 0:
            start = max(0, pos - 300)
            snippet = wikitext[start:pos]
            try:
                plain = mwparserfromhell.parse(snippet).strip_code()
            except Exception:
                plain = snippet
            sentences = re.split(r"(?<=[.!?])\s+", plain.strip())
            claim_text = sentences[-1].strip() if sentences else plain[-200:].strip()
        else:
            claim_text = ""
        citations.append(Citation(id=str(i), url=url, claim_text=claim_text))
    return citations


async def fetch_article(url: str) -> WikiArticle:
    """
    Fetch article content, sections, and citations.
    Uses wikipedia-api for clean section text; prop=extlinks for comprehensive citation URLs.
    """
    cache_ns = f"article_v2:{cache_key(url)}"
    if cache_ns in cache:
        return WikiArticle.model_validate(cache[cache_ns])

    title = _title_from_url(url)

    # Fetch wikitext (for citations) and extlinks (all external URLs) in parallel
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        wt_resp, el_resp = await asyncio.gather(
            client.get(MEDIAWIKI_API, params={
                "action": "query", "titles": title,
                "prop": "revisions", "rvprop": "content",
                "rvslots": "main", "format": "json", "formatversion": "2",
            }),
            client.get(MEDIAWIKI_API, params={
                "action": "query", "titles": title,
                "prop": "extlinks", "ellimit": "max",
                "format": "json", "formatversion": "2",
            }),
        )
        wt_resp.raise_for_status()
        el_resp.raise_for_status()

    wt_pages = wt_resp.json().get("query", {}).get("pages", [])
    if not wt_pages or "revisions" not in wt_pages[0]:
        raise ValueError(f"Article not found or has no content: {title!r}")

    wikitext = wt_pages[0]["revisions"][0]["slots"]["main"]["content"]
    canonical_title = wt_pages[0]["title"]
    canonical_url = f"https://en.wikipedia.org/wiki/{canonical_title.replace(' ', '_')}"

    el_pages = el_resp.json().get("query", {}).get("pages", [])
    extlinks = [el["url"] for el in el_pages[0].get("extlinks", [])] if el_pages else []

    # Use wikipedia-api for clean plain-text sections; fall back to wikitext parsing
    loop = asyncio.get_event_loop()
    page = await loop.run_in_executor(None, _wiki.page, canonical_title)
    if page.exists():
        section_names, section_texts = _sections_from_page(page)
    else:
        section_names, section_texts = _parse_sections_from_wikitext(wikitext)

    citations = _build_citations(extlinks, wikitext)

    article = WikiArticle(
        title=canonical_title,
        url=canonical_url,
        wikitext=wikitext,
        sections=section_names,
        section_texts=section_texts,
        citations=citations,
        assessment_class=None,
    )
    cache.set(cache_ns, article.model_dump(), expire=3600)
    return article


async def fetch_edit_history(title: str) -> list[dict]:
    """Fetch the last 500 edits for an article via MediaWiki API."""
    cache_ns = f"edit_history:{cache_key(title)}"
    if cache_ns in cache:
        return cache[cache_ns]

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        resp = await client.get(MEDIAWIKI_API, params={
            "action": "query", "titles": title,
            "prop": "revisions", "rvprop": "ids|timestamp|user|comment|tags",
            "rvlimit": "500", "format": "json", "formatversion": "2",
        })
        resp.raise_for_status()

    pages = resp.json().get("query", {}).get("pages", [])
    result = pages[0].get("revisions", []) if pages else []
    cache.set(cache_ns, result, expire=3600)
    return result


async def fetch_talk_page(title: str) -> str:
    """Fetch talk page wikitext, including up to 5 archive pages."""
    cache_ns = f"talk_page:{cache_key(title)}"
    if cache_ns in cache:
        return cache[cache_ns]

    talk_title = f"Talk:{title}"
    page_titles = [talk_title] + [f"{talk_title}/Archive {n}" for n in range(1, 6)]
    texts: list[str] = []

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        for page_title in page_titles:
            resp = await client.get(MEDIAWIKI_API, params={
                "action": "query", "titles": page_title,
                "prop": "revisions", "rvprop": "content",
                "rvslots": "main", "format": "json", "formatversion": "2",
            })
            resp.raise_for_status()
            pages = resp.json().get("query", {}).get("pages", [])
            if pages and "revisions" in pages[0]:
                texts.append(pages[0]["revisions"][0]["slots"]["main"]["content"])

    result = "\n\n".join(texts)
    cache.set(cache_ns, result, expire=3600)
    return result
