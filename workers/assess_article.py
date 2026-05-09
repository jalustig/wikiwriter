# ABOUTME: Makes the key editorial decisions about what a Wikipedia article needs.
# ABOUTME: Produces ArticleAssessment — the WHAT that edit_planner translates into HOW.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache, cache_key, record_llm_call
from models import (
    WikiArticle, ArticleSummary, ContentGrade, EditorialEnvironment,
    SourceEvaluation, ArticleAssessment, ArticleImportance, SectionDecision,
)

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "assess_article.txt").read_text()
_MODEL = os.getenv("DRAFT_MODEL", "gpt-4o")


def _source_quality_summary(source_evals: list[SourceEvaluation]) -> str:
    if not source_evals:
        return "No existing sources to evaluate."
    usable = sum(1 for s in source_evals if s.recommendation == "USE")
    weak = sum(1 for s in source_evals if s.recommendation == "WEAK")
    dead = sum(1 for s in source_evals if s.status == "DEAD")
    total = len(source_evals)
    return (
        f"{total} existing citations: {usable} reliable, {weak} weak, {dead} dead. "
        + ("Strong source base." if usable / max(total, 1) > 0.6
           else "Many citations need replacement or supplementation.")
    )


async def assess_article(
    article: WikiArticle,
    summary: ArticleSummary,
    grade: ContentGrade,
    environment: EditorialEnvironment,
    source_evals: list[SourceEvaluation],
) -> ArticleAssessment:
    key = cache_key(
        "assess_article",
        article.url,
        grade.overall_score,
        environment.caution_level,
    )
    if key in cache:
        return ArticleAssessment.model_validate(cache[key])

    dimension_scores = "\n".join(
        f"- {dim}: {score:.1f}" for dim, score in grade.dimension_scores.items()
    )
    section_scores = "\n".join(
        f"- {name}: {grade.section_grades.get(name, 5.0):.1f}" for name in article.sections
    )
    editor_norms = "\n".join(f"- {n}" for n in environment.editor_imposed_norms) or "None"
    policies = "\n".join(f"- {p}" for p in environment.policies_and_restrictions) or "None"
    flip = ", ".join(environment.flip_flopped_sections) or "None"
    disputes = json.dumps(environment.active_disputes) if environment.active_disputes else "None"

    prompt = _PROMPT.format(
        article_title=article.title,
        article_topic=summary.topic,
        article_scope=summary.scope,
        letter_grade=grade.letter_grade,
        overall_score=grade.overall_score,
        assessment_class=article.assessment_class or "unrated",
        dimension_scores=dimension_scores,
        section_scores=section_scores,
        grade_narrative=grade.narrative,
        caution_level=environment.caution_level,
        flip_flopped_sections=flip,
        editor_norms=editor_norms,
        policies_and_restrictions=policies,
        active_disputes=disputes,
        environment_narrative=environment.environment_narrative,
        source_quality_summary=_source_quality_summary(source_evals),
    )

    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    record_llm_call(response.usage)

    raw = json.loads(response.choices[0].message.content)

    importance = ArticleImportance(
        tier=raw["importance"]["tier"],
        rationale=raw["importance"]["rationale"],
        expected_depth=raw["importance"]["expected_depth"],
    )

    sections = [
        SectionDecision(
            name=s["name"],
            action=s["action"],
            edit_type=s.get("edit_type"),
            rationale=s["rationale"],
        )
        for s in raw.get("sections", [])
    ]

    # Enforce: never include flip-flopped sections as EDIT
    flip_set = set(environment.flip_flopped_sections)
    sections = [
        s if s.name not in flip_set else SectionDecision(
            name=s.name, action="SKIP",
            edit_type=None, rationale="flip-flopped section — do not edit"
        )
        for s in sections
    ]

    result = ArticleAssessment(
        importance=importance,
        article_class=raw.get("article_class", "DEVELOPING"),
        effort_ceiling=raw.get("effort_ceiling", "MODERATE"),
        edit_scope=raw.get("edit_scope", "SPECIFIC_SECTIONS"),
        sections=sections,
        primary_weaknesses=raw.get("primary_weaknesses", []),
        source_quality_summary=raw.get("source_quality_summary", ""),
        edit_rationale=raw.get("edit_rationale", ""),
    )
    cache.set(key, result.model_dump(), expire=3600)
    return result
