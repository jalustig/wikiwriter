# ABOUTME: Orchestrator — runs all workers in sequence and emits ProgressEvents.
# ABOUTME: Yields events as an async generator; writes a verbose per-run log to logs/.

import asyncio
import json
import os
import re
from datetime import datetime, timezone

from cache import get_cache_stats, reset_cache_stats
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
from workers.narrator import narrate


def _think(stage: str, message: str) -> ProgressEvent:
    return ProgressEvent(stage=stage, status="thinking", message=message)


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
        """Wrap _run with verbose per-run logging to logs/."""
        os.makedirs("logs", exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "_", url.lower())[:60].strip("_")
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        start = datetime.now(timezone.utc)
        reset_cache_stats()

        with open(f"logs/{ts}_{slug}.jsonl", "w") as log:
            def _write(entry: dict) -> None:
                log.write(json.dumps(entry) + "\n")
                log.flush()

            _write({
                "type": "run_start",
                "url": url,
                "started_at": start.isoformat(),
            })

            async for event in self._run(url):
                elapsed = round((datetime.now(timezone.utc) - start).total_seconds(), 2)
                stats = get_cache_stats()
                entry: dict = {
                    "type": "event",
                    "t": elapsed,
                    "stage": event.stage,
                    "status": event.status,
                    "message": event.message,
                    "cache": stats,
                }
                if event.status == "done" and event.data:
                    entry["summary"] = self._log_summary(event)
                _write(entry)
                yield event

            _write({
                "type": "run_end",
                "t": round((datetime.now(timezone.utc) - start).total_seconds(), 2),
                "cache": get_cache_stats(),
            })

    def _log_summary(self, event: ProgressEvent) -> dict:
        """Condense event.data into log-friendly key metrics."""
        d = event.data or {}
        if event.stage == "INTAKE":
            g = d.get("grade", {})
            r = d.get("risk", {})
            return {
                "grade": g.get("letter_grade"), "score": g.get("overall_score"),
                "risk_tier": r.get("risk_tier"), "revert_rate": r.get("revert_rate_12mo"),
                "flip_flopped": r.get("flip_flopped_sections", []),
            }
        if event.stage == "PLAN":
            plan = d.get("plan", {})
            return {
                "sections_to_edit": [s["name"] for s in plan.get("sections_to_edit", [])],
                "sections_excluded": plan.get("sections_excluded", []),
            }
        if event.stage == "CLAIMS":
            claims = d.get("claim_map", {}).get("claims", [])
            from collections import Counter
            counts = Counter(c["status"] for c in claims)
            return dict(counts)
        if event.stage == "SOURCES":
            audit = d.get("audit", [])
            new = d.get("new_sources", [])
            recs = [a["recommendation"] for a in audit]
            from collections import Counter
            return {"audit_breakdown": dict(Counter(recs)), "new_sources_found": len(new)}
        if event.stage == "CRITIQUE":
            c = d.get("critique", {})
            return {
                "verdict": c.get("overall_verdict"),
                "dimensions": {k: v["verdict"] for k, v in c.get("dimension_results", {}).items()},
            }
        if event.stage == "GRADE":
            p = d.get("proposal", {})
            return {
                "input_grade": p.get("input_grade", {}).get("letter_grade"),
                "output_grade": p.get("output_grade", {}).get("letter_grade"),
                "quality_delta": p.get("quality_delta"),
            }
        return {}

    async def _run(self, url: str):
        # ── Stage 1: Fetch ────────────────────────────────────────────────
        yield ProgressEvent(stage="FETCH", status="running", message=f"Fetching {url}...")
        article = await fetch_article(url)
        n_sections = len(article.sections)
        n_citations = len(article.citations)
        intro_text = next((v for k, v in article.section_texts.items() if not k), "")
        thought = await narrate("fetch", {
            "article_title": article.title,
            "assessment_class": article.assessment_class or "unrated",
            "n_sections": n_sections,
            "n_citations": n_citations,
            "sections": article.sections[:12],
            "intro_text": intro_text[:600],
        })
        if thought:
            yield _think("FETCH", thought)
        yield ProgressEvent(
            stage="FETCH",
            status="done",
            message=f"'{article.title}' — {n_sections} sections, {n_citations} citations",
        )

        # ── Stage 2: Intake (parallel) ────────────────────────────────────
        yield ProgressEvent(
            stage="INTAKE",
            status="running",
            message="Assessing article quality and reading the editorial history...",
        )
        content_grade, editorial_risk = await asyncio.gather(
            self.article_grader.run(article),
            self.editorial_analyzer.run(article),
        )
        worst_dim = min(content_grade.dimension_scores, key=content_grade.dimension_scores.get)
        thought = await narrate("quality_and_risk", {
            "article_title": article.title,
            "grade": content_grade.letter_grade,
            "overall_score": content_grade.overall_score,
            "dimension_scores": content_grade.dimension_scores,
            "weakest_dimension": worst_dim,
            "weakest_score": content_grade.dimension_scores[worst_dim],
            "risk_tier": editorial_risk.risk_tier,
            "revert_rate": editorial_risk.revert_rate_12mo,
            "edit_velocity": editorial_risk.edit_velocity,
            "flip_flopped_sections": editorial_risk.flip_flopped_sections,
            "grade_narrative": content_grade.narrative,
        })
        if thought:
            yield _think("INTAKE", thought)
        grade_summary = f"{content_grade.letter_grade} ({content_grade.overall_score:.1f}/10)"
        yield ProgressEvent(
            stage="INTAKE",
            status="done",
            message=f"Grade: {grade_summary} | Risk: {editorial_risk.risk_tier}",
            data={"grade": content_grade.model_dump(), "risk": editorial_risk.model_dump()},
        )

        # ── Stage 3: Planning ─────────────────────────────────────────────
        yield ProgressEvent(stage="PLAN", status="running", message="Planning edits...")
        plan = await self.planner.run(article, content_grade, editorial_risk)
        thought = await narrate("planning", {
            "article_title": article.title,
            "sections_to_edit": [
                {"name": s.name, "modes": s.modes, "rationale": s.rationale}
                for s in plan.sections_to_edit
            ],
            "sections_excluded": plan.sections_excluded,
            "exclusion_reasons": plan.exclusion_reasons,
            "plan_narrative": plan.narrative,
        })
        if thought:
            yield _think("PLAN", thought)
        n_edit = len(plan.sections_to_edit)
        n_excl = len(plan.sections_excluded)
        yield ProgressEvent(
            stage="PLAN",
            status="done",
            message=f"Editing {n_edit} sections, leaving {n_excl} untouched",
            data={"plan": plan.model_dump(), "article": article.model_dump()},
        )

        if not plan.sections_to_edit:
            yield ProgressEvent(
                stage="PLAN",
                status="error",
                message=f"Nothing to edit — {editorial_risk.risk_tier} risk tier.",
            )
            return

        # ── Stage 4: Claim extraction ─────────────────────────────────────
        yield ProgressEvent(stage="CLAIMS", status="running", message="Tagging claims by citation status...")
        claim_map = await self.claim_extractor.run(article, plan)
        uncited_claims = [c for c in claim_map.claims if c.status in ("uncited", "undercited")]
        n_claims = len(claim_map.claims)
        n_uncited = len(uncited_claims)
        thought = await narrate("claims", {
            "n_claims_total": n_claims,
            "n_uncited": n_uncited,
            "sample_uncited": [c.text[:80] for c in uncited_claims[:3]],
        })
        if thought:
            yield _think("CLAIMS", thought)
        yield ProgressEvent(
            stage="CLAIMS",
            status="done",
            message=f"{n_claims} claims tagged — {n_uncited} need sources",
            data={"claim_map": claim_map.model_dump()},
        )

        # ── Stage 5: Source audit and discovery ───────────────────────────
        n_cit = len(article.citations)
        n_discover = len(uncited_claims[:5])
        total_tasks = n_cit + n_discover
        yield ProgressEvent(
            stage="SOURCES",
            status="running",
            message=f"Evaluating sources (0/{total_tasks})...",
        )
        yield _think("SOURCES", (
            f"Auditing {n_cit} existing citations for quality, recency and relevance "
            f"while searching for new sources to cover {n_discover} uncited claims."
        ))

        async def _tagged(kind: str, coro):
            try:
                return kind, await coro
            except Exception as exc:
                return kind, exc

        all_tasks = (
            [asyncio.create_task(_tagged("audit", self.source_evaluator.evaluate(
                c.url, c.claim_text, article.title))) for c in article.citations] +
            [asyncio.create_task(_tagged("discovery", self.source_discovery.find_sources(
                claim.text, article.title))) for claim in uncited_claims[:5]]
        )

        audit_results: list[SourceEvaluation] = []
        discovery_results_nested: list = []
        completed = 0

        for future in asyncio.as_completed(all_tasks):
            kind, result = await future
            completed += 1

            if not isinstance(result, Exception):
                if kind == "audit":
                    audit_results.append(result)
                    r = result
                    if r.status == "DEAD":
                        yield _think("SOURCES", f"Dead link: {r.url}")
                    else:
                        note = r.claim_support_summary[:70] if r.claim_support_summary else ""
                        msg = f"{r.domain_type} [{r.overall_score:.1f}] → {r.recommendation}"
                        yield _think("SOURCES", msg + (f" — {note}" if note else ""))
                elif kind == "discovery":
                    discovery_results_nested.append(result)
                    for s in result:
                        yield _think("SOURCES", (
                            f"New source: {s.domain_type} [{s.overall_score:.1f}] "
                            f"— {s.claim_support_summary[:160]}"
                        ))

            yield ProgressEvent(
                stage="SOURCES",
                status="running",
                message=f"Evaluating sources ({completed}/{total_tasks})...",
                data={"source_result": result.model_dump()} if not isinstance(result, Exception)
                and kind == "audit" else None,
            )

        new_sources = [s for group in discovery_results_nested for s in group]
        n_usable = sum(1 for r in audit_results if r.recommendation == "USE")
        n_dead = sum(1 for r in audit_results if r.status == "DEAD")
        thought = await narrate("sources_complete", {
            "n_audited": len(audit_results),
            "n_usable": n_usable,
            "n_dead": n_dead,
            "n_new": len(new_sources),
            "rejected": [r.url[:50] for r in audit_results if r.recommendation == "REJECT"],
        })
        if thought:
            yield _think("SOURCES", thought)
        yield ProgressEvent(
            stage="SOURCES",
            status="done",
            message=f"{n_usable} usable citations, {len(new_sources)} new sources found",
            data={
                "audit": [r.model_dump() for r in audit_results],
                "new_sources": [r.model_dump() for r in new_sources],
            },
        )

        source_report = _assemble_source_report(audit_results, new_sources)

        # ── Stage 6: Drafting ─────────────────────────────────────────────
        n_edit = len(plan.sections_to_edit)
        yield ProgressEvent(
            stage="DRAFT",
            status="running",
            message=f"Writing {n_edit} section drafts...",
        )
        for s in plan.sections_to_edit:
            yield _think("DRAFT", f"Drafting '{s.name}' — {', '.join(s.modes)}: {s.rationale}")

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

        thought = await narrate("drafts_complete", {
            "n_drafted": len(section_drafts),
            "n_failed": n_edit - len(section_drafts),
            "sections": [d.section_name for d in section_drafts],
            "changes_summary": [d.changes_made[:2] for d in section_drafts],
        })
        if thought:
            yield _think("DRAFT", thought)
        yield ProgressEvent(
            stage="DRAFT",
            status="done",
            message=f"{len(section_drafts)} sections drafted and merged",
            data={
                "section_drafts": [d.model_dump() for d in section_drafts],
                "assembled": assembled,
            },
        )

        # ── Stage 7: Critique ─────────────────────────────────────────────
        yield ProgressEvent(stage="CRITIQUE", status="running", message="Reviewing draft quality...")
        sections_edited = [d.section_name for d in section_drafts]
        critique, final_draft, critique_events = await self._critique_loop(
            assembled, source_report, sections_edited=sections_edited
        )
        for e in critique_events:
            yield e
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

        # ── Stage 8: Grading ──────────────────────────────────────────────
        yield ProgressEvent(stage="GRADE", status="running", message="Scoring the final output...")
        output_grade = await self.output_grader.run(final_draft, article)
        quality_delta = output_grade.overall_score - content_grade.overall_score
        thought = await narrate("grade_complete", {
            "input_grade": content_grade.letter_grade,
            "input_score": content_grade.overall_score,
            "output_grade": output_grade.letter_grade,
            "output_score": output_grade.overall_score,
            "quality_delta": quality_delta,
            "dimension_deltas": {
                k: round(output_grade.dimension_scores.get(k, 0) - v, 1)
                for k, v in content_grade.dimension_scores.items()
            },
        })
        if thought:
            yield _think("GRADE", thought)
        yield ProgressEvent(
            stage="GRADE",
            status="done",
            message=f"Output: {output_grade.letter_grade} (Δ {quality_delta:+.1f})",
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
            message="Edit proposal ready for review.",
            data={"proposal": proposal.model_dump()},
        )

    async def _critique_loop(
        self,
        draft: str,
        source_report: str,
        sections_edited: list[str] | None = None,
        cycles: int = 0,
    ) -> tuple[CritiqueResult, str, list[ProgressEvent]]:
        events: list[ProgressEvent] = []

        if cycles >= 2:
            events.append(_think("CRITIQUE", (
                "Draft failed critique twice — issues are too fundamental to fix by revision. Discarding."
            )))
            return CritiqueResult(
                overall_verdict="DISCARD",
                dimension_results={},
                revision_instructions=[],
                discard_reason="Failed critique twice — fundamental issues not resolvable by revision",
            ), draft, events

        if cycles > 0:
            events.append(_think("CRITIQUE", f"Revision cycle {cycles}: re-checking the draft."))

        critique = await self.critic.run(draft, source_report, sections_edited=sections_edited)

        failed_dims = [k for k, v in critique.dimension_results.items() if v.verdict == "FAIL"]
        passed_dims = [k for k, v in critique.dimension_results.items() if v.verdict == "PASS"]

        for dim in passed_dims:
            events.append(_think("CRITIQUE", (
                f"✓ {dim.replace('_', ' ').title()}: {critique.dimension_results[dim].notes}"
            )))
        for dim in failed_dims:
            events.append(_think("CRITIQUE", (
                f"✗ {dim.replace('_', ' ').title()}: {critique.dimension_results[dim].notes}"
            )))

        if critique.overall_verdict == "PASS":
            events.append(_think("CRITIQUE", "All quality checks passed. Draft is ready."))
            return critique, draft, events

        if critique.overall_verdict == "REVISE":
            n_issues = len(critique.revision_instructions)
            plural = "s" if n_issues > 1 else ""
            msg = f"Needs revision — {n_issues} issue{plural} to address. Revising..."
            events.append(_think("CRITIQUE", msg))
            revised = await self.draft_writer.revise(draft, critique.revision_instructions, source_report)
            sub_critique, sub_draft, sub_events = await self._critique_loop(
                revised, source_report, sections_edited=sections_edited, cycles=cycles + 1
            )
            return sub_critique, sub_draft, events + sub_events

        return critique, draft, events

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
        original_text = "\n\n".join(article.section_texts.get(s, "") for s in article.sections)
        full_diff = _build_diff(original_text, final_draft)

        edited_sections = [d.section_name for d in section_drafts if d.changes_made]
        summary_parts = [f"AI-assisted edit: improved {', '.join(edited_sections[:3])}"]
        if len(edited_sections) > 3:
            summary_parts.append(f"and {len(edited_sections) - 3} more sections")
        new_urls = [s.url for s in new_sources[:3]]
        if new_urls:
            summary_parts.append(f"Added sources: {', '.join(new_urls)}")
        summary_parts.append("([[Wikipedia:Bots/Requests for approval/WikiWriter|WikiWriter AI]])")

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
            disclosure_edit_summary=". ".join(summary_parts),
        )
