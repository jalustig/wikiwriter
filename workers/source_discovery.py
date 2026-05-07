# ABOUTME: Finds new sources for uncited or poorly-cited claims via web search.
# ABOUTME: Returns ranked SourceEvaluation list for each sourcing gap.

import asyncio

from models import SourceEvaluation
from tools.search import search
from workers.source_evaluator import SourceEvaluator


class SourceDiscovery:
    def __init__(self):
        self.evaluator = SourceEvaluator()

    async def find_sources(
        self,
        claim: str,
        article_title: str,
        max_candidates: int = 5,
    ) -> list[SourceEvaluation]:
        query = f"{claim} {article_title} wikipedia source"
        results = await search(query, max_results=max_candidates)

        urls = [r["url"] for r in results if r.get("url")]
        if not urls:
            return []

        evaluations = await asyncio.gather(
            *[self.evaluator.evaluate(url, claim, article_title) for url in urls],
            return_exceptions=True,
        )

        live_results = [
            e for e in evaluations
            if isinstance(e, SourceEvaluation) and e.status != "DEAD"
        ]
        live_results.sort(key=lambda e: e.overall_score, reverse=True)
        return live_results[:3]
