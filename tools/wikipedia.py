# ABOUTME: MediaWiki API client for fetching article content, edit history, and talk pages.
# ABOUTME: Returns typed WikiArticle objects. All results cached.

import re
import httpx
import mwparserfromhell

from cache import cached
from models import WikiArticle, Citation

MEDIAWIKI_API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "WikiWriter/1.0"}


def _title_from_url(url: str) -> str:
    """Extract article title from a Wikipedia URL or return the input as-is."""
    match = re.match(r"https?://en\.wikipedia\.org/wiki/(.+)", url)
    if match:
        return match.group(1).replace("_", " ")
    return url


def _parse_sections(wikitext: str) -> tuple[list[str], dict[str, str]]:
    """Parse wikitext into ordered section names and a name→wikitext mapping."""
    parsed = mwparserfromhell.parse(wikitext)
    sections = parsed.get_sections(include_lead=True, flat=True)

    section_names = []
    section_texts = {}

    for section in sections:
        headings = section.filter_headings()
        if headings:
            name = headings[0].title.strip()
        else:
            name = "Lead"
        # Avoid duplicate names
        unique_name = name
        suffix = 2
        while unique_name in section_texts:
            unique_name = f"{name} ({suffix})"
            suffix += 1
        section_names.append(unique_name)
        section_texts[unique_name] = str(section)

    return section_names, section_texts


def _parse_citations(wikitext: str) -> list[Citation]:
    """Extract Citation objects from cite templates in wikitext."""
    parsed = mwparserfromhell.parse(wikitext)
    citations = []
    seen_urls: set[str] = set()

    for i, template in enumerate(parsed.filter_templates()):
        name = template.name.strip().lower()
        if not name.startswith("cite"):
            continue
        if not template.has("url"):
            continue
        url = str(template.get("url").value).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        # Find surrounding sentence in plain text for claim_text
        # Use a small window of text around the template in the wikitext
        raw = str(wikitext)
        tmpl_str = str(template)
        pos = raw.find(tmpl_str)
        if pos >= 0:
            start = max(0, pos - 200)
            snippet = raw[start:pos]
            # Take the last sentence fragment before the template
            sentences = re.split(r"(?<=[.!?])\s+", snippet)
            claim_text = sentences[-1].strip() if sentences else snippet[:200].strip()
        else:
            claim_text = ""

        citations.append(Citation(id=str(i), url=url, claim_text=claim_text))

    return citations


@cached("article", ttl=3600)
async def fetch_article(url: str) -> WikiArticle:
    """Fetch article wikitext via MediaWiki API and return a WikiArticle."""
    title = _title_from_url(url)
    params = {
        "action": "query",
        "titles": title,
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "format": "json",
        "formatversion": "2",
    }
    async with httpx.AsyncClient(headers=HEADERS) as client:
        resp = await client.get(MEDIAWIKI_API, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

    pages = data["query"]["pages"]
    page = pages[0]
    wikitext = page["revisions"][0]["slots"]["main"]["content"]
    canonical_title = page["title"]
    canonical_url = f"https://en.wikipedia.org/wiki/{canonical_title.replace(' ', '_')}"

    section_names, section_texts = _parse_sections(wikitext)
    citations = _parse_citations(wikitext)

    return WikiArticle(
        title=canonical_title,
        url=canonical_url,
        wikitext=wikitext,
        sections=section_names,
        section_texts=section_texts,
        citations=citations,
        assessment_class=None,
    )


@cached("edit_history", ttl=3600)
async def fetch_edit_history(title: str) -> list[dict]:
    """Fetch the last 500 edits for an article via MediaWiki API."""
    params = {
        "action": "query",
        "titles": title,
        "prop": "revisions",
        "rvprop": "ids|timestamp|user|comment|tags",
        "rvlimit": "500",
        "format": "json",
        "formatversion": "2",
    }
    async with httpx.AsyncClient(headers=HEADERS) as client:
        resp = await client.get(MEDIAWIKI_API, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

    pages = data["query"]["pages"]
    page = pages[0]
    return page.get("revisions", [])


@cached("talk_page", ttl=3600)
async def fetch_talk_page(title: str) -> str:
    """Fetch talk page wikitext, including up to 5 archive pages."""
    talk_title = f"Talk:{title}"
    texts = []

    async with httpx.AsyncClient(headers=HEADERS) as client:
        # Main talk page
        params = {
            "action": "query",
            "titles": talk_title,
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "format": "json",
            "formatversion": "2",
        }
        resp = await client.get(MEDIAWIKI_API, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        page = data["query"]["pages"][0]
        if "revisions" in page:
            texts.append(page["revisions"][0]["slots"]["main"]["content"])

        # Archive pages
        for n in range(1, 6):
            archive_title = f"{talk_title}/Archive {n}"
            params["titles"] = archive_title
            resp = await client.get(MEDIAWIKI_API, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            page = data["query"]["pages"][0]
            if "missing" not in page and "revisions" in page:
                texts.append(page["revisions"][0]["slots"]["main"]["content"])

    return "\n\n".join(texts)
