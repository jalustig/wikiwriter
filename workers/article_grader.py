# ABOUTME: Scores a Wikipedia article on 7 content quality dimensions.
# ABOUTME: Same rubric is applied to output drafts to compute quality delta.

import json
import os
import openai
from pathlib import Path
from dotenv import load_dotenv

from cache import cache, cache_key
from models import WikiArticle, ContentGrade

DIMENSION_WEIGHTS = {
    "citation_coverage": 0.20,
    "citation_quality": 0.15,
    "npov": 0.20,
    "prose_quality": 0.15,
    "structural_completeness": 0.15,
    "freshness": 0.10,
    "lead_quality": 0.05,
}


_PROMPT_TEMPLATE = (Path(__file__).parent.parent / "prompts" / "article_grader.txt").read_text()
_WIKITEXT_LIMIT = 12000


def _build_grader_prompt(article_title: str, wikitext: str) -> str:
    return _PROMPT_TEMPLATE.format(
        article_title=article_title,
        sections_text=wikitext[:_WIKITEXT_LIMIT],
    )


def _letter_grade(score: float) -> str:
    if score >= 8.5:
        return "A"
    if score >= 7.0:
        return "B"
    if score >= 5.5:
        return "C"
    if score >= 4.0:
        return "D"
    return "F"


class ArticleGrader:
    def __init__(self):
        load_dotenv()
        self.client = openai.AsyncOpenAI()
        self.model = os.getenv("DRAFT_MODEL", "gpt-4o")

    async def run(self, article: WikiArticle) -> ContentGrade:
        cache_ns = cache_key("article_grader_v2", article.url, article.wikitext[:500])
        if cache_ns in cache:
            cached = cache[cache_ns]
            dim = cached.get("dimension_scores", {})
            cached["overall_score"] = sum(dim[d] * w for d, w in DIMENSION_WEIGHTS.items() if d in dim)
            cached["letter_grade"] = _letter_grade(cached["overall_score"])
            return ContentGrade.model_validate(cached)

        prompt = _build_grader_prompt(article.title, article.wikitext)

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )

        data = json.loads(response.choices[0].message.content)

        dimension_scores = data.get("dimension_scores", {})
        for dim in DIMENSION_WEIGHTS:
            if dim not in dimension_scores:
                print(f"Warning: missing dimension {dim}, defaulting to 5.0")
                dimension_scores[dim] = 5.0
        data["dimension_scores"] = dimension_scores

        overall = sum(dimension_scores[d] * w for d, w in DIMENSION_WEIGHTS.items())
        data["overall_score"] = overall
        data["letter_grade"] = _letter_grade(overall)

        grade = ContentGrade.model_validate(data)
        cache[cache_ns] = grade.model_dump()
        return grade
