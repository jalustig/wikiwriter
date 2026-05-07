# ABOUTME: Scores a Wikipedia article on 7 content quality dimensions.
# ABOUTME: Same rubric is applied to output drafts to compute quality delta.

import json
import os
import openai
from pathlib import Path
from dotenv import load_dotenv

from cache import cache, cache_key
from models import WikiArticle, ContentGrade


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
            return ContentGrade.model_validate(cache[key])

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

        # Enforce letter grade mapping regardless of what the model returns
        overall = float(data["overall_score"])
        data["letter_grade"] = _letter_grade(overall)

        grade = ContentGrade.model_validate(data)
        cache[key] = grade.model_dump()
        return grade
