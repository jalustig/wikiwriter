# ABOUTME: Produces a human-readable narrative of the editorial approach and changes made.
# ABOUTME: Written as a talk-page note explaining WHY and WHAT changed, not just a diff.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache, cache_key
from models import WikiArticle, ArticleAssessment, SectionDraft, CritiqueResult, EditSummary

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "summarize_edit.txt").read_text()
_MODEL = os.getenv("DRAFT_MODEL", "gpt-4o")


def _changes_per_section(drafts: list[SectionDraft]) -> str:
    lines = []
    for d in drafts:
        changes = "; ".join(d.changes_made[:3]) if d.changes_made else "text revised"
        cites_added = f", citations added: {', '.join(d.citations_added[:3])}" if d.citations_added else ""
        lines.append(f"- {d.section_name}: {changes}{cites_added}")
    return "\n".join(lines)


async def summarize_edit(
    article: WikiArticle,
    assessment: ArticleAssessment,
    drafts: list[SectionDraft],
    critique: CritiqueResult,
) -> EditSummary:
    key = cache_key(
        "summarize_edit",
        article.url,
        [d.section_name for d in drafts],
        critique.overall_verdict,
    )
    if key in cache:
        return EditSummary.model_validate(cache[key])

    sections_changed = [d.section_name for d in drafts if d.changes_made]

    prompt = _PROMPT.format(
        article_title=article.title,
        assessment_rationale=assessment.edit_rationale,
        sections_changed=", ".join(sections_changed),
        changes_per_section=_changes_per_section(drafts),
        critique_verdict=critique.overall_verdict,
        passing_sections=", ".join(critique.passing_sections) or "all",
        failing_sections=", ".join(critique.failing_sections) or "none",
    )

    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    raw = json.loads(response.choices[0].message.content)
    result = EditSummary(
        narrative=raw.get("narrative", "Edit completed."),
        sections_changed=raw.get("sections_changed", sections_changed),
        disclosure_line=raw.get(
            "disclosure_line",
            "AI-assisted Wikipedia edit ([[Wikipedia:Bots/Requests_for_approval/WikiWriter|WikiWriter AI]])",
        ),
    )
    cache.set(key, result.model_dump(), expire=3600)
    return result
