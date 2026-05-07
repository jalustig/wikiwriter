# ABOUTME: Sentence-level claim parser for Wikipedia article sections.
# ABOUTME: Tags each claim as cited/undercited/uncited/consensus-uncited via LLM.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache_key, cache
from models import WikiArticle, ImprovementPlan, Claim, ClaimMap

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "claim_extractor.txt").read_text()
_MODEL = os.getenv("FAST_MODEL", "gpt-5.4")


def _sections_to_analyze(article: WikiArticle, plan: ImprovementPlan) -> list[str]:
    """Return planned section names that have non-empty text, in article order."""
    planned = {s.name for s in plan.sections_to_edit}
    return [
        name for name in article.sections
        if name in planned and article.section_texts.get(name, "").strip()
    ]


def _deduplicate_claims(claims: list[Claim]) -> list[Claim]:
    """Remove duplicate claims by text, preserving first occurrence and order."""
    seen: set[str] = set()
    result: list[Claim] = []
    for claim in claims:
        if claim.text not in seen:
            seen.add(claim.text)
            result.append(claim)
    return result


class ClaimExtractor:
    async def run(self, article: WikiArticle, plan: ImprovementPlan) -> ClaimMap:
        sections = _sections_to_analyze(article, plan)
        if not sections:
            return ClaimMap(claims=[])

        cache_ns = f"claim_extractor_v2:{cache_key(article.url, sorted(sections))}"
        if cache_ns in cache:
            return ClaimMap.model_validate(cache[cache_ns])

        all_claims: list[Claim] = []
        for section_name in sections:
            section_text = article.section_texts[section_name]
            # Include wikitext snippet for citation context when available
            wikitext_snippet = _extract_wikitext_section(article.wikitext, section_name)

            prompt = _PROMPT.format(
                article_title=article.title,
                section_name=section_name,
                section_text=section_text,
                wikitext_snippet=wikitext_snippet or "(not available)",
            )

            response = await _client.chat.completions.create(
                model=_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            raw = json.loads(response.choices[0].message.content)
            for item in raw.get("claims", []):
                try:
                    all_claims.append(Claim(
                        text=item["text"],
                        status=item["status"],
                        citation_id=item.get("citation_id"),
                    ))
                except (KeyError, ValueError):
                    continue

        claims = _deduplicate_claims(all_claims)
        result = ClaimMap(claims=claims)
        cache.set(cache_ns, result.model_dump(), expire=3600)
        return result


def _extract_wikitext_section(wikitext: str, section_name: str) -> str | None:
    """Extract raw wikitext for a named section (up to 4000 chars)."""
    import re
    # Lead has no heading in wikitext — extract everything before the first == heading
    if section_name == "Lead":
        first_heading = re.search(r"^==", wikitext, re.MULTILINE)
        end = first_heading.start() if first_heading else len(wikitext)
        return wikitext[:end][:4000] or None

    # Match section header at any level
    pattern = rf"==+\s*{re.escape(section_name)}\s*==+"
    match = re.search(pattern, wikitext, re.MULTILINE)
    if not match:
        return None
    start = match.start()
    level = len(re.match(r"(=+)", match.group()).group(1))
    # Search for next same-or-higher heading starting after the current heading line
    after_heading = wikitext.find("\n", start) + 1
    next_heading = re.search(r"^={1," + str(level) + r"}[^=]", wikitext[after_heading:], re.MULTILINE)
    end = after_heading + next_heading.start() if next_heading else len(wikitext)
    return wikitext[start:end][:4000]
