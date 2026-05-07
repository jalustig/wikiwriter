# ABOUTME: Pipeline coordinator — runs all workers in sequence and emits ProgressEvents.
# ABOUTME: Yields events as an async generator for the Streamlit app to consume.

import asyncio

from models import ProgressEvent
from tools.wikipedia import fetch_article
from workers.article_grader import ArticleGrader
from workers.editorial_context import EditorialContextAnalyzer
from workers.planner import Planner
from workers.claim_extractor import ClaimExtractor
from workers.source_evaluator import SourceEvaluator
from workers.source_discovery import SourceDiscovery


class WikiWriterOrchestrator:
    def __init__(self):
        self.article_grader = ArticleGrader()
        self.editorial_analyzer = EditorialContextAnalyzer()
        self.planner = Planner()
        self.claim_extractor = ClaimExtractor()
        self.source_evaluator = SourceEvaluator()
        self.source_discovery = SourceDiscovery()

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

        # Stage 4: Claim extraction
        yield ProgressEvent(stage="CLAIMS", status="running", message="Extracting and tagging claims...")
        claim_map = await self.claim_extractor.run(article, plan)
        uncited_claims = [c for c in claim_map.claims if c.status in ("uncited", "undercited")]
        n_claims = len(claim_map.claims)
        n_uncited = len(uncited_claims)
        yield ProgressEvent(
            stage="CLAIMS",
            status="done",
            message=f"Found {n_claims} claims; {n_uncited} need sources",
            data={"claim_map": claim_map.model_dump()},
        )

        # Stage 5: Source audit and discovery
        n_cit = len(article.citations)
        yield ProgressEvent(
            stage="SOURCES",
            status="running",
            message=f"Auditing {n_cit} citations and searching for {n_uncited} uncited claims...",
        )

        audit_tasks = [
            self.source_evaluator.evaluate(c.url, c.claim_text, article.title)
            for c in article.citations
        ]
        discovery_tasks = [
            self.source_discovery.find_sources(claim.text, article.title)
            for claim in uncited_claims[:5]
        ]

        all_results = await asyncio.gather(*audit_tasks, *discovery_tasks, return_exceptions=True)
        audit_results = [r for r in all_results[:len(audit_tasks)] if not isinstance(r, Exception)]
        discovery_results_nested = [r for r in all_results[len(audit_tasks):] if not isinstance(r, Exception)]
        new_sources = [s for group in discovery_results_nested for s in group]

        for r in audit_results:
            yield ProgressEvent(
                stage="SOURCES",
                status="running",
                message=f"  {r.recommendation} [{r.overall_score:.1f}] {r.url[:70]}",
                data={"source_result": r.model_dump()},
            )

        n_usable = sum(1 for r in audit_results if r.recommendation == "USE")
        yield ProgressEvent(
            stage="SOURCES",
            status="done",
            message=f"Sources: {n_usable} usable existing, {len(new_sources)} new candidates found",
            data={
                "audit": [r.model_dump() for r in audit_results],
                "new_sources": [r.model_dump() for r in new_sources],
            },
        )
