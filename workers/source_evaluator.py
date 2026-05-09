# ABOUTME: Evaluates any URL as a potential Wikipedia source on 5 quality dimensions.
# ABOUTME: Used by both citation audit (existing sources) and research_section (new candidates).

import asyncio
import json
import os
from pathlib import Path

import openai
from dotenv import load_dotenv

from cache import cache, cache_key, record_llm_start, record_llm_tokens
from models import SourceEvaluation, ArticleSummary
from tools.fetcher import fetch_readable
from tools.wayback import get_archive_url

SOURCE_WEIGHTS = {
    "domain_type": 0.25,
    "topic_relevance": 0.35,
    "age": 0.15,
    "credibility": 0.15,
    "accessibility": 0.10,
}


def _recommendation(overall_score: float) -> str:
    if overall_score >= 7.0:
        return "USE"
    if overall_score >= 4.5:
        return "WEAK"
    return "REJECT"


class SourceEvaluator:
    def __init__(self):
        load_dotenv()
        self.client = openai.AsyncOpenAI()
        self.model = os.getenv("DRAFT_MODEL", "gpt-4o")
        with open(Path(__file__).parent.parent / "prompts" / "source_evaluator.txt") as f:
            self.prompt_template = f.read()

    async def evaluate(
        self,
        url: str,
        article_summary: ArticleSummary,
    ) -> SourceEvaluation:
        eval_key = cache_key("source_evaluator_v2", url, article_summary.topic[:80])
        if eval_key in cache:
            return SourceEvaluation.model_validate(cache[eval_key])

        # Try to fetch the page
        status = "DEAD"
        page_text = ""
        try:
            page_text = await fetch_readable(url)
            status = "LIVE"
        except Exception:
            archive_url = await get_archive_url(url)
            if archive_url:
                try:
                    page_text = await fetch_readable(archive_url)
                    status = "ARCHIVED"
                except Exception:
                    pass

        if status == "DEAD":
            result = SourceEvaluation(
                url=url,
                status="DEAD",
                domain_type="other",
                scores={k: 0.0 for k in SOURCE_WEIGHTS},
                overall_score=0.0,
                topic_coverage_summary="Source is inaccessible and has no archive copy.",
                recommendation="REJECT",
            )
            cache.set(eval_key, result.model_dump(), expire=7 * 24 * 3600)
            return result

        prompt = self.prompt_template.format(
            url=url,
            status=status,
            topic=article_summary.topic,
            scope=article_summary.scope,
            page_text=page_text[:6000],
        )

        for attempt in range(3):
            try:
                record_llm_start()
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    timeout=60.0,
                )
                break
            except openai.APITimeoutError:
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        record_llm_tokens(response.usage)

        data = json.loads(response.choices[0].message.content)
        scores = data.get("scores", {})

        for dim in SOURCE_WEIGHTS:
            if dim not in scores:
                scores[dim] = 0.0

        overall = sum(scores[d] * w for d, w in SOURCE_WEIGHTS.items())

        result = SourceEvaluation(
            url=url,
            status=status,
            domain_type=data.get("domain_type", "other"),
            scores=scores,
            overall_score=overall,
            author=data.get("author"),
            publication=data.get("publication"),
            publication_date=data.get("publication_date"),
            topic_coverage_summary=data.get("topic_coverage_summary", ""),
            recommendation=_recommendation(overall),
            claims=data.get("claims", []),
        )

        cache.set(eval_key, result.model_dump(), expire=7 * 24 * 3600)
        return result
