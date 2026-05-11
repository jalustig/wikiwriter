# ABOUTME: Makes the key editorial decisions about what a Wikipedia article needs.
# ABOUTME: Produces ArticleAssessment — the WHAT that edit_planner translates into HOW.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache, cache_key, record_llm_start, record_llm_tokens
from utils.log import log_llm_call, log_llm_response
from models import (
    WikiArticle, ArticleSummary, ContentGrade, EditorialEnvironment,
    SourceEvaluation, ArticleAssessment, ArticleImportance, SectionDecision,
)

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "assess_article.txt").read_text()
_MODEL = os.getenv("DRAFT_MODEL", "gpt-4o")

_MAX_EDIT_SECTIONS = 3


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


def _enforce_section_cap(sections: list[SectionDecision]) -> list[SectionDecision]:
    """Demote excess EDIT sections to SKIP, keeping at most _MAX_EDIT_SECTIONS."""
    edits = [s for s in sections if s.action == "EDIT"]
    skips = [s for s in sections if s.action == "SKIP"]
    if len(edits) <= _MAX_EDIT_SECTIONS:
        return sections
    kept = edits[:_MAX_EDIT_SECTIONS]
    demoted = [
        SectionDecision(
            name=s.name, action="SKIP", edit_type=None,
            rationale=f"Deprioritised — {s.rationale}"
        )
        for s in edits[_MAX_EDIT_SECTIONS:]
    ]
    return kept + demoted + skips


def _parse_sections(raw_list: list, flip_flopped: set) -> list[SectionDecision]:
    sections = []
    for s in raw_list:
        if isinstance(s, str):
            s = {"name": s, "action": "EDIT", "rationale": ""}
        name = s["name"]
        action = "SKIP" if name in flip_flopped else s.get("action", "SKIP")
        rationale = ("flip-flopped section — do not edit" if name in flip_flopped
                     else s.get("rationale", ""))
        sections.append(SectionDecision(
            name=name,
            action=action,
            edit_type=s.get("edit_type") if action == "EDIT" else None,
            rationale=rationale,
        ))
    return sections


def _build_assessment(raw: dict, flip_flopped: set) -> ArticleAssessment:
    """Build ArticleAssessment from parsed LLM response dict."""
    importance = ArticleImportance(
        tier=raw["importance"]["tier"],
        rationale=raw["importance"]["rationale"],
        expected_depth=raw["importance"]["expected_depth"],
    )

    no_edit = bool(raw.get("no_edit", False))

    if no_edit:
        sections = []
        would_edit = _parse_sections(raw.get("would_edit_sections", []), flip_flopped)
    else:
        sections = _parse_sections(raw.get("sections", []), flip_flopped)
        sections = _enforce_section_cap(sections)
        # Keep SKIP entries only if they were flip-flopped (useful for display); drop others
        flip_skips = {s.name for s in sections if s.action == "SKIP" and s.name in flip_flopped}
        sections = [s for s in sections if s.action == "EDIT" or s.name in flip_skips]
        would_edit = []

    return ArticleAssessment(
        importance=importance,
        article_class=raw.get("article_class", "DEVELOPING"),
        effort_ceiling=raw.get("effort_ceiling", "MODERATE"),
        edit_scope=raw.get("edit_scope", "SPECIFIC_SECTIONS"),
        sections=sections,
        primary_weaknesses=raw.get("primary_weaknesses", []),
        source_quality_summary=raw.get("source_quality_summary", ""),
        source_trust_verdict=raw.get("source_trust_verdict", ""),
        edit_rationale=raw.get("edit_rationale", ""),
        no_edit=no_edit,
        no_edit_reason=raw.get("no_edit_reason", ""),
        would_edit_sections=would_edit,
        scope_of_work=raw.get("scope_of_work", ""),
    )


_ENDMATTER = {
    "references", "citations", "sources", "notes", "bibliography",
    "further reading", "external links", "see also",
}


def _build_section_scores(sections: list[str], section_grades: dict[str, float]) -> str:
    """Return per-section score lines, excluding end-matter sections."""
    return "\n".join(
        f"- {name}: {section_grades.get(name, 5.0):.1f}"
        for name in sections
        if name.lower() not in _ENDMATTER
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
    section_scores = _build_section_scores(article.sections, grade.section_grades)
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

    log_llm_call("assess_article", _MODEL, prompt)
    record_llm_start()
    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    record_llm_tokens(response.usage)
    raw_text = response.choices[0].message.content
    log_llm_response("assess_article", raw_text,
                     getattr(response.usage, "prompt_tokens", 0),
                     getattr(response.usage, "completion_tokens", 0))
    raw = json.loads(raw_text)
    flip_set = set(environment.flip_flopped_sections)
    result = _build_assessment(raw, flip_set)
    cache.set(key, result.model_dump(), expire=3600)
    return result
