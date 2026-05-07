# ABOUTME: Pipeline coordinator — runs all workers in sequence and emits ProgressEvents.
# ABOUTME: Yields events as an async generator for the Streamlit app to consume.

import asyncio

from models import ProgressEvent
from tools.wikipedia import fetch_article
from workers.article_grader import ArticleGrader
from workers.editorial_context import EditorialContextAnalyzer
from workers.planner import Planner


class WikiWriterOrchestrator:
    def __init__(self):
        self.article_grader = ArticleGrader()
        self.editorial_analyzer = EditorialContextAnalyzer()
        self.planner = Planner()

    async def run(self, url: str):
        # Stage 1: Fetch article
        yield ProgressEvent(stage="FETCH", status="running", message=f"Fetching {url}...")
        article = await fetch_article(url)
        n_sections = len(article.sections)
        n_citations = len(article.citations)
        yield ProgressEvent(
            stage="FETCH",
            status="done",
            message=f"Loaded '{article.title}' — {n_sections} sections, {n_citations} citations",
        )

        # Stage 2: Parallel intake
        yield ProgressEvent(
            stage="INTAKE",
            status="running",
            message="Grading article and analyzing editorial environment...",
        )
        content_grade, editorial_risk = await asyncio.gather(
            self.article_grader.run(article),
            self.editorial_analyzer.run(article),
        )
        grade_summary = f"{content_grade.letter_grade} ({content_grade.overall_score:.1f}/10)"
        yield ProgressEvent(
            stage="INTAKE",
            status="done",
            message=f"Grade: {grade_summary} | Risk: {editorial_risk.risk_tier}",
            data={"grade": content_grade.model_dump(), "risk": editorial_risk.model_dump()},
        )

        # Stage 3: Planning
        yield ProgressEvent(stage="PLAN", status="running", message="Planning edits...")
        plan = await self.planner.run(article, content_grade, editorial_risk)
        n_edit = len(plan.sections_to_edit)
        n_excl = len(plan.sections_excluded)
        yield ProgressEvent(
            stage="PLAN",
            status="done",
            message=f"Plan: editing {n_edit} sections, excluding {n_excl}",
            data={"plan": plan.model_dump(), "article": article.model_dump()},
        )

        if not plan.sections_to_edit:
            yield ProgressEvent(
                stage="PLAN",
                status="error",
                message=f"No sections to edit. Reason: {editorial_risk.risk_tier} risk tier.",
            )
            return
