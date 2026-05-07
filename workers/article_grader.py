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
        with open(Path(__file__).parent.parent / "prompts" / "article_grader.txt") as f:
            self.prompt_template = f.read()

    async def run(self, article: WikiArticle) -> ContentGrade:
        key = cache_key("article_grader", article.url, article.wikitext[:500])
        if key in cache:
            cached = cache[key]
            dim = cached.get("dimension_scores", {})
            cached["overall_score"] = sum(dim[d] * w for d, w in DIMENSION_WEIGHTS.items() if d in dim)
            cached["letter_grade"] = _letter_grade(cached["overall_score"])
            return ContentGrade.model_validate(cached)

        sections_text = "\n\n".join(
            f"== {name} ==\n{text[:1000]}"
            for name, text in article.section_texts.items()
        )
        prompt = self.prompt_template.format(
            article_title=article.title,
            sections_text=sections_text,
        )

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )

        data = json.loads(response.choices[0].message.content)

        dimension_scores = data.get("dimension_scores", {})
        for key in DIMENSION_WEIGHTS:
            if key not in dimension_scores:
                print(f"Warning: missing dimension {key}, defaulting to 5.0")
                dimension_scores[key] = 5.0
        data["dimension_scores"] = dimension_scores

        overall = sum(dimension_scores[d] * w for d, w in DIMENSION_WEIGHTS.items())
        data["overall_score"] = overall
        data["letter_grade"] = _letter_grade(overall)

        grade = ContentGrade.model_validate(data)
        cache[key] = grade.model_dump()
        return grade
