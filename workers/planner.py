# ABOUTME: Generates an improvement plan from content grade and editorial risk profile.
# ABOUTME: The plan determines which sections to edit and with what modes.

import json
import os
from pathlib import Path

import openai
from dotenv import load_dotenv

from cache import cache, cache_key, record_llm_start, record_llm_tokens
from models import WikiArticle, ContentGrade, EditorialRiskProfile, ImprovementPlan, SectionPlan


def _apply_hard_rules(
    article: WikiArticle,
    risk: EditorialRiskProfile,
) -> tuple[list[str], dict[str, str], list[str]]:
    """
    Apply pre-LLM hard rules and return (excluded_sections, exclusion_reasons, remaining_sections).

    Rule 1: CRITICAL risk tier — exclude all sections.
    Rule 2: Flip-flopped sections — always excluded.
    """
    excluded: list[str] = []
    reasons: dict[str, str] = {}

    if risk.risk_tier == "CRITICAL":
        for section in article.sections:
            excluded.append(section)
            reasons[section] = "CRITICAL risk tier — article skipped"
        return excluded, reasons, []

    flip_set = set(risk.flip_flopped_sections)
    remaining: list[str] = []
    for section in article.sections:
        if section in flip_set:
            excluded.append(section)
            reasons[section] = "flip-flop conflict — do not edit"
        else:
            remaining.append(section)

    return excluded, reasons, remaining


class Planner:
    def __init__(self):
        load_dotenv()
        self.client = openai.AsyncOpenAI()
        self.model = os.getenv("DRAFT_MODEL", "gpt-4o")
        with open(Path(__file__).parent.parent / "prompts" / "planner.txt") as f:
            self.prompt_template = f.read()

    async def run(
        self,
        article: WikiArticle,
        content_grade: ContentGrade,
        editorial_risk: EditorialRiskProfile,
    ) -> ImprovementPlan:
        key = cache_key(
            "planner",
            article.url,
            content_grade.overall_score,
            editorial_risk.risk_tier,
        )
        if key in cache:
            return ImprovementPlan.model_validate(cache[key])

        pre_excluded, pre_reasons, remaining = _apply_hard_rules(article, editorial_risk)

        # CRITICAL risk: return immediately without LLM
        if editorial_risk.risk_tier == "CRITICAL":
            plan = ImprovementPlan(
                sections_to_edit=[],
                sections_excluded=pre_excluded,
                exclusion_reasons=pre_reasons,
                narrative="Article skipped due to CRITICAL editorial risk tier.",
            )
            cache[key] = plan.model_dump()
            return plan

        llm_result = await self._call_llm(article, content_grade, editorial_risk, remaining)

        # Merge hard-rule exclusions with LLM exclusions
        all_excluded = pre_excluded + llm_result.get("sections_excluded", [])
        all_reasons = {**pre_reasons, **llm_result.get("exclusion_reasons", {})}

        plan = ImprovementPlan(
            sections_to_edit=[
                SectionPlan(**s) for s in llm_result.get("sections_to_edit", [])
            ],
            sections_excluded=all_excluded,
            exclusion_reasons=all_reasons,
            narrative=llm_result.get("narrative", ""),
        )
        cache[key] = plan.model_dump()
        return plan

    async def _call_llm(
        self,
        article: WikiArticle,
        content_grade: ContentGrade,
        editorial_risk: EditorialRiskProfile,
        candidate_sections: list[str],
    ) -> dict:
        dimension_scores = "\n".join(
            f"- {dim}: {score:.1f}"
            for dim, score in content_grade.dimension_scores.items()
        )
        section_scores = "\n".join(
            f"- {name}: {content_grade.section_grades.get(name, 5.0):.1f}"
            for name in candidate_sections
        )
        candidate_list = "\n".join(f"- {name}" for name in candidate_sections)
        editor_norms = (
            "\n".join(f"- {norm}" for norm in editorial_risk.editor_imposed_norms)
            if editorial_risk.editor_imposed_norms
            else "None"
        )

        prompt = self.prompt_template.format(
            article_title=article.title,
            dimension_scores=dimension_scores,
            section_scores=section_scores,
            risk_tier=editorial_risk.risk_tier,
            editor_norms=editor_norms,
            candidate_sections=candidate_list,
        )

        record_llm_start()
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        record_llm_tokens(response.usage)

        return json.loads(response.choices[0].message.content)
