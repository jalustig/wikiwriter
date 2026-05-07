# ABOUTME: Assembles section drafts into a coherent full article text.
# ABOUTME: Integrates revised sections, sharpens the lead, and removes redundancy.

import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache_key, cache
from models import WikiArticle, SectionDraft

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "synthesis_writer.txt").read_text()
_MODEL = os.getenv("DRAFT_MODEL", "gpt-5.4")


def _assemble_with_drafts(article: WikiArticle, section_drafts: list[SectionDraft]) -> str:
    """Substitute revised section texts into the article, preserving untouched sections."""
    revised_by_name = {d.section_name: d.revised_text for d in section_drafts}
    parts: list[str] = []
    for name in article.sections:
        text = revised_by_name.get(name) or article.section_texts.get(name, "")
        if text.strip():
            header = f"== {name} ==" if name != "Lead" else ""
            if header:
                parts.append(f"{header}\n{text}")
            else:
                parts.append(text)
    return "\n\n".join(parts)


class SynthesisWriter:
    async def run(
        self,
        article: WikiArticle,
        section_drafts: list[SectionDraft],
        source_report: str,
    ) -> str:
        assembled = _assemble_with_drafts(article, section_drafts)

        draft_names = sorted(d.section_name for d in section_drafts)
        cache_ns = f"synthesis:{cache_key(article.url, draft_names, source_report)}"
        if cache_ns in cache:
            return cache[cache_ns]

        changes_summary = "\n".join(
            f"- {d.section_name}: {'; '.join(d.changes_made[:3])}"
            for d in section_drafts
        )

        prompt = _PROMPT.format(
            article_title=article.title,
            assembled_text=assembled,
            changes_summary=changes_summary,
            source_report=source_report or "No sources available.",
        )

        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        result = response.choices[0].message.content.strip()
        cache.set(cache_ns, result, expire=3600)
        return result
