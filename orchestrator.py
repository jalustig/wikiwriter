# ABOUTME: Pipeline coordinator — runs all workers in sequence and emits ProgressEvents.
# ABOUTME: Yields events as an async generator for the Streamlit app to consume.

import asyncio

from models import ProgressEvent, WikiArticle, ContentGrade, EditorialRiskProfile
from models import ImprovementPlan, SourceEvaluation, SectionDraft, CritiqueResult, EditProposal
from tools.wikipedia import fetch_article
from workers.article_grader import ArticleGrader
from workers.editorial_context import EditorialContextAnalyzer
from workers.planner import Planner
from workers.claim_extractor import ClaimExtractor
from workers.source_evaluator import SourceEvaluator
from workers.source_discovery import SourceDiscovery
from workers.draft_writer import DraftWriter, _assemble_source_report, _build_diff
from workers.synthesis_writer import SynthesisWriter
from workers.critic import Critic
from workers.output_grader import OutputGrader


class WikiWriterOrchestrator:
    def __init__(self):
        self.article_grader = ArticleGrader()
        self.editorial_analyzer = EditorialContextAnalyzer()
        self.planner = Planner()
        self.claim_extractor = ClaimExtractor()
        self.source_evaluator = SourceEvaluator()
        self.source_discovery = SourceDiscovery()
        self.draft_writer = DraftWriter()
        self.synthesis_writer = SynthesisWriter()
        self.critic = Critic()
        self.output_grader = OutputGrader()

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

        source_report = _assemble_source_report(audit_results, new_sources)

        # Stage 6: Parallel section drafting
        n_edit = len(plan.sections_to_edit)
        yield ProgressEvent(
            stage="DRAFT",
            status="running",
            message=f"Drafting {n_edit} sections in parallel...",
        )
        draft_tasks = [
            self.draft_writer.run(
                section_plan=s,
                article=article,
                source_report=source_report,
                editor_norms=editorial_risk.editor_imposed_norms,
            )
            for s in plan.sections_to_edit
        ]
        draft_results = await asyncio.gather(*draft_tasks, return_exceptions=True)
        section_drafts = [r for r in draft_results if not isinstance(r, Exception)]

        assembled = await self.synthesis_writer.run(article, section_drafts, source_report)

        yield ProgressEvent(
            stage="DRAFT",
            status="done",
            message=f"Drafted {len(section_drafts)} sections; synthesis complete",
            data={
                "section_drafts": [d.model_dump() for d in section_drafts],
                "assembled": assembled,
            },
        )

        # Stage 7: Critique loop (max 2 revisions)
        yield ProgressEvent(stage="CRITIQUE", status="running", message="Running critique...")
        critique, final_draft = await self._critique_loop(assembled, source_report)
        yield ProgressEvent(
            stage="CRITIQUE",
            status="done",
            message=f"Verdict: {critique.overall_verdict}",
            data={"critique": critique.model_dump()},
        )

        if critique.overall_verdict == "DISCARD":
            yield ProgressEvent(
                stage="CRITIQUE",
                status="error",
                message=f"Edit discarded: {critique.discard_reason}",
            )
            return

        # Stage 8: Output grading + proposal assembly
        yield ProgressEvent(stage="GRADE", status="running", message="Grading final output...")
        output_grade = await self.output_grader.run(final_draft, article)
        quality_delta = output_grade.overall_score - content_grade.overall_score
        yield ProgressEvent(
            stage="GRADE",
            status="done",
            message=f"Output grade: {output_grade.letter_grade} (Δ {quality_delta:+.1f})",
        )

        proposal = self._build_proposal(
            article=article,
            content_grade=content_grade,
            output_grade=output_grade,
            editorial_risk=editorial_risk,
            plan=plan,
            audit_results=audit_results,
            new_sources=new_sources,
            section_drafts=section_drafts,
            critique=critique,
            final_draft=final_draft,
        )
        yield ProgressEvent(
            stage="GRADE",
            status="done",
            message="Pipeline complete.",
            data={"proposal": proposal.model_dump()},
        )

    async def _critique_loop(
        self, draft: str, source_report: str, cycles: int = 0
    ) -> tuple[CritiqueResult, str]:
        if cycles >= 2:
            return CritiqueResult(
                overall_verdict="DISCARD",
                dimension_results={},
                revision_instructions=[],
                discard_reason="Failed critique twice — fundamental issues not resolvable by revision",
            ), draft
        critique = await self.critic.run(draft, source_report)
        if critique.overall_verdict == "PASS":
            return critique, draft
        if critique.overall_verdict == "REVISE":
            revised = await self.draft_writer.revise(
                draft, critique.revision_instructions, source_report
            )
            return await self._critique_loop(revised, source_report, cycles + 1)
        return critique, draft

    def _build_proposal(
        self,
        article: WikiArticle,
        content_grade: ContentGrade,
        output_grade: ContentGrade,
        editorial_risk: EditorialRiskProfile,
        plan: ImprovementPlan,
        audit_results: list[SourceEvaluation],
        new_sources: list[SourceEvaluation],
        section_drafts: list[SectionDraft],
        critique: CritiqueResult,
        final_draft: str,
    ) -> EditProposal:
        original_text = "\n\n".join(
            article.section_texts.get(s, "") for s in article.sections
        )
        full_diff = _build_diff(original_text, final_draft)

        edited_sections = [d.section_name for d in section_drafts if d.changes_made]
        summary_parts = [f"AI-assisted edit: improved {', '.join(edited_sections[:3])}"]
        if len(edited_sections) > 3:
            summary_parts.append(f"and {len(edited_sections) - 3} more sections")
        new_urls = [s.url for s in new_sources[:3]]
        if new_urls:
            summary_parts.append(f"Added sources: {', '.join(new_urls)}")
        summary_parts.append("([[Wikipedia:Bots/Requests for approval/WikiWriter|WikiWriter AI]])")
        disclosure_edit_summary = ". ".join(summary_parts)

        return EditProposal(
            article=article,
            input_grade=content_grade,
            output_grade=output_grade,
            quality_delta=round(output_grade.overall_score - content_grade.overall_score, 2),
            editorial_risk=editorial_risk,
            improvement_plan=plan,
            source_audit=audit_results,
            new_sources=new_sources,
            section_drafts=section_drafts,
            critique=critique,
            full_diff=full_diff,
            disclosure_edit_summary=disclosure_edit_summary,
        )
