# ABOUTME: Grades the final assembled draft using the same rubric as the input article grader.
# ABOUTME: Returns ContentGrade for quality delta calculation.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache_key, cache, record_llm_call
from models import WikiArticle, ContentGrade
from workers.article_grader import DIMENSION_WEIGHTS, _letter_grade

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "output_grader.txt").read_text()
_MODEL = os.getenv("FAST_MODEL", "gpt-5.4")


class OutputGrader:
    async def run(self, assembled_draft: str, original_article: WikiArticle) -> ContentGrade:
        cache_ns = f"output_grader:{cache_key(assembled_draft)}"
        if cache_ns in cache:
            return ContentGrade.model_validate(cache[cache_ns])

        prompt = _PROMPT.format(
            article_title=original_article.title,
            assembled_draft=assembled_draft[:8000],
        )

        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        record_llm_call(response.usage)

        raw = json.loads(response.choices[0].message.content)
        dimension_scores: dict[str, float] = {
            k: float(v)
            for k, v in raw.get("dimension_scores", {}).items()
            if k in DIMENSION_WEIGHTS
        }
        for dim in DIMENSION_WEIGHTS:
            if dim not in dimension_scores:
                dimension_scores[dim] = 5.0

        overall_score = sum(
            dimension_scores[dim] * weight
            for dim, weight in DIMENSION_WEIGHTS.items()
        )
        section_grades = {
            name: float(score)
            for name, score in raw.get("section_grades", {}).items()
        }

        result = ContentGrade(
            overall_score=round(overall_score, 2),
            letter_grade=_letter_grade(overall_score),
            section_grades=section_grades,
            dimension_scores=dimension_scores,
            narrative=raw.get("narrative", ""),
        )
        cache.set(cache_ns, result.model_dump(), expire=3600)
        return result
