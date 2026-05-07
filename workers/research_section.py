# ABOUTME: Compound task that extracts claims from a section and finds sources for uncited ones.
# ABOUTME: Uses LLM relevance ranking to select top URLs before fetching.

import asyncio
import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache, cache_key
from models import WikiArticle, ArticleSummary, SectionResearch, Claim, SourceEvaluation
from tools.search import search
from workers.source_evaluator import SourceEvaluator
from workers.source_discovery import _is_allowed_source_url

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_RANK_PROMPT = (Path(__file__).parent.parent / "prompts" / "research_section.txt").read_text()
_MODEL = os.getenv("FAST_MODEL", "gpt-5.4")

_SEARCH_CANDIDATES = 20
_LLM_SELECT = 5
_MAX_RETRIES = 2


def _extract_claims_from_section(article: WikiArticle, section_name: str) -> list[Claim]:
    """Lightweight claim extraction based on citation pattern in wikitext."""
    from workers.claim_extractor import _extract_wikitext_section
    import re

    section_text = article.section_texts.get(section_name, "")
    wikitext = _extract_wikitext_section(article.wikitext, section_name) or ""

    # Find sentences and check if they have a nearby <ref>
    sentences = re.split(r"(?<=[.!?])\s+", section_text.strip())
    claims = []
    for sent in sentences:
        sent = sent.strip()
        if not sent or len(sent) < 20:
            continue
        # Check if this sentence appears near a citation in wikitext
        escaped = re.escape(sent[:40])
        has_ref = bool(re.search(escaped + r"[^.!?]*?<ref", wikitext, re.IGNORECASE))
        status = "cited" if has_ref else "uncited"
        claims.append(Claim(text=sent, status=status))

    return claims


async def _rank_urls(
    claim_text: str,
    article_title: str,
    article_summary: ArticleSummary,
    search_results: list[dict],
    max_select: int = _LLM_SELECT,
) -> list[str]:
    """Ask the LLM to pick the top URLs from search result snippets."""
    result_lines = "\n".join(
        f"{i+1}. [{r.get('title', '')}] {r['url']}\n   {r.get('content', '')[:200]}"
        for i, r in enumerate(search_results)
    )

    prompt = _RANK_PROMPT.format(
        article_title=article_title,
        article_topic=article_summary.topic,
        article_scope=article_summary.scope,
        section_name="",
        claim_text=claim_text,
        search_results=result_lines,
        max_select=max_select,
    )

    try:
        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        content = response.choices[0].message.content.strip()
        # Extract JSON array from response
        import re
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            urls = json.loads(match.group())
            return [u for u in urls if isinstance(u, str)][:max_select]
    except Exception:
        pass

    # Fallback: just return first N URLs from search results
    return [r["url"] for r in search_results[:max_select]]


async def research_section(
    article: WikiArticle,
    section_name: str,
    article_summary: ArticleSummary,
) -> SectionResearch:
    key = cache_key("research_section_v2", article.url, section_name)
    if key in cache:
        return SectionResearch.model_validate(cache[key])

    # Step 1: Use full LLM claim extractor for accurate citation tagging
    from workers.claim_extractor import ClaimExtractor
    from models import ImprovementPlan, SectionPlan

    plan = ImprovementPlan(
        sections_to_edit=[SectionPlan(name=section_name, modes=["Citation Repair"], rationale="")],
        sections_excluded=[],
        exclusion_reasons={},
        narrative="",
    )
    claim_map = await ClaimExtractor().run(article, plan)

    uncited = [c for c in claim_map.claims if c.status in ("uncited", "undercited")]

    if not uncited:
        result = SectionResearch(section_name=section_name, claim_map=claim_map, new_sources=[])
        cache.set(key, result.model_dump(), expire=3600)
        return result

    # Step 2: Find sources for uncited claims
    evaluator = SourceEvaluator()
    all_new_sources: list[SourceEvaluation] = []
    seen_urls: set[str] = set()

    for claim in uncited[:5]:  # limit claims to avoid explosion
        query = f"{claim.text[:100]} {article.title}"

        for attempt in range(_MAX_RETRIES + 1):
            search_results = await search(query, max_results=_SEARCH_CANDIDATES)
            search_results = [r for r in search_results if _is_allowed_source_url(r.get("url", ""))]

            if not search_results:
                break

            ranked_urls = await _rank_urls(
                claim.text, article.title, article_summary, search_results
            )

            eval_tasks = [
                evaluator.evaluate(url, article_summary)
                for url in ranked_urls
                if url not in seen_urls
            ]
            if not eval_tasks:
                break

            evals = await asyncio.gather(*eval_tasks, return_exceptions=True)
            usable = [
                e for e in evals
                if isinstance(e, SourceEvaluation) and e.status != "DEAD"
                and e.recommendation in ("USE", "WEAK")
            ]

            for e in usable:
                if e.url not in seen_urls:
                    seen_urls.add(e.url)
                    all_new_sources.append(e)

            if len(usable) >= 2:
                break  # enough sources, no need to retry

            # Retry with broader query
            query = f"{article.title} {claim.text[:50]}"

    # Deduplicate and rank
    all_new_sources.sort(key=lambda s: s.overall_score, reverse=True)
    top_sources = all_new_sources[:10]

    result = SectionResearch(
        section_name=section_name,
        claim_map=claim_map,
        new_sources=top_sources,
    )
    cache.set(key, result.model_dump(), expire=3600)
    return result
