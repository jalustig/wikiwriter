# ABOUTME: DAG-based orchestrator — assess WHAT, plan HOW, execute DAG, critique, revise.
# ABOUTME: Emits ProgressEvents as async generator; writes verbose per-run log to logs/.

import asyncio
import difflib
import json
import os
import re
from datetime import datetime, timezone

from cache import get_cache_stats, reset_cache_stats
from dag import DAGExecutor, build_dag
from models import (
    ProgressEvent, WikiArticle, ArticleSummary, ContentGrade, EditorialEnvironment,
    SourceEvaluation, ArticleAssessment, SectionResearch, SectionDraft,
    CritiqueResult, SectionCritiqueResult, EditSummary, EditProposal, TaskNode,
)
from tools.wikipedia import fetch_article
from workers.article_grader import ArticleGrader
from workers.editorial_context import EditorialContextAnalyzer
from workers.summarize_article import summarize_article
from workers.assess_article import assess_article
from workers.edit_planner import plan_edits, format_dag_for_display
from workers.plan_validate import validate_plan
from workers.research_section import research_section
from workers.source_evaluator import SourceEvaluator
from workers.draft_writer import DraftWriter, _build_diff
from workers.synthesis_writer import SynthesisWriter, _assemble_with_drafts
from workers.critique_section import critique_section
from workers.aggregate_critique import aggregate_critique
from workers.summarize_edit import summarize_edit
from workers.output_grader import OutputGrader
from workers.narrator import narrate


def _think(stage: str, message: str) -> ProgressEvent:
    return ProgressEvent(stage=stage, status="thinking", message=message)


def _assemble_source_report(
    audit: list[SourceEvaluation],
    new_sources: list[SourceEvaluation],
    section_research: list[SectionResearch] | None = None,
) -> str:
    lines: list[str] = []
    usable = [s for s in audit if s.recommendation in ("USE", "WEAK")]
    if usable:
        lines.append("EXISTING CITATIONS (usable):")
        for s in usable:
            tag = "WEAK" if s.recommendation == "WEAK" else "USE"
            lines.append(f"  [{tag} {s.overall_score:.1f}] {s.url}")
            lines.append(f"    {s.topic_coverage_summary}")
        lines.append("")
    if new_sources:
        lines.append("NEW SOURCES (from research):")
        for s in new_sources:
            lines.append(f"  [{s.overall_score:.1f}] {s.url}")
            lines.append(f"    {s.topic_coverage_summary}")
        lines.append("")
    if section_research:
        for sr in section_research:
            if sr.new_sources:
                lines.append(f"SECTION '{sr.section_name}' SOURCES:")
                for s in sr.new_sources:
                    lines.append(f"  [{s.overall_score:.1f}] {s.url}")
                    lines.append(f"    {s.topic_coverage_summary}")
                lines.append("")
    return "\n".join(lines)


class WikiWriterOrchestrator:

    def __init__(self):
        self.grader = ArticleGrader()
        self.env_analyzer = EditorialContextAnalyzer()
        self.source_evaluator = SourceEvaluator()
        self.draft_writer = DraftWriter()
        self.synthesis_writer = SynthesisWriter()
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

            _write({"type": "run_start", "url": url, "started_at": start.isoformat()})

            async for event in self._run(url):
                elapsed = round((datetime.now(timezone.utc) - start).total_seconds(), 2)
                entry: dict = {
                    "type": "event",
                    "t": elapsed,
                    "stage": event.stage,
                    "status": event.status,
                    "message": event.message,
                    "cache": get_cache_stats(),
                }
                _write(entry)
                yield event

            _write({
                "type": "run_end",
                "t": round((datetime.now(timezone.utc) - start).total_seconds(), 2),
                "cache": get_cache_stats(),
            })

    async def _run(self, url: str):
        # ── FETCH ─────────────────────────────────────────────────────────────
        yield ProgressEvent(stage="FETCH", status="running", message=f"Fetching {url}...")
        article = await fetch_article(url)
        thought = await narrate("fetch", {
            "article_title": article.title,
            "assessment_class": article.assessment_class or "unrated",
            "n_sections": len(article.sections),
            "n_citations": len(article.citations),
            "sections": article.sections[:12],
            "intro_text": next((v for k, v in article.section_texts.items() if not k), "")[:600],
        })
        if thought:
            yield _think("FETCH", thought)
        yield ProgressEvent(
            stage="FETCH", status="done",
            message=f"'{article.title}' — {len(article.sections)} sections, {len(article.citations)} citations",
        )

        # ── GATHER EVIDENCE (parallel) ────────────────────────────────────────
        yield ProgressEvent(stage="GATHER", status="running", message="Gathering evidence in parallel...")

        # summarize_article must run first
        article_summary = await summarize_article(article)
        yield _think("GATHER", f"Topic: {article_summary.topic[:120]}")

        # Now all parallel tasks
        n_cit = min(len(article.citations), 20)
        yield _think("GATHER", f"Grading article, reading editorial history, evaluating {n_cit} citations...")

        async def _eval_source(citation):
            return await self.source_evaluator.evaluate(citation.url, article_summary)

        grade_task = asyncio.create_task(self.grader.run(article))
        env_task = asyncio.create_task(self.env_analyzer.run(article))
        source_tasks = [
            asyncio.create_task(_eval_source(c))
            for c in article.citations[:20]
        ]

        content_grade, environment = await asyncio.gather(grade_task, env_task)
        source_results = await asyncio.gather(*source_tasks, return_exceptions=True)
        source_evals = [r for r in source_results if isinstance(r, SourceEvaluation)]

        n_usable = sum(1 for s in source_evals if s.recommendation == "USE")
        n_dead = sum(1 for s in source_evals if s.status == "DEAD")

        yield ProgressEvent(
            stage="GATHER", status="done",
            message=f"Grade: {content_grade.letter_grade} ({content_grade.overall_score:.1f}) | "
                    f"Caution: {environment.caution_level} | "
                    f"Sources: {n_usable} usable, {n_dead} dead",
            data={
                "grade": content_grade.model_dump(),
                "environment": environment.model_dump(),
                "audit": [s.model_dump() for s in source_evals],
                "article": article.model_dump(),
                "article_summary": article_summary.model_dump(),
            },
        )

        # ── ASSESS (WHAT) ────────────────────────────────────────────────────
        yield ProgressEvent(stage="ASSESS", status="running", message="Assessing what the article needs...")
        assessment = await assess_article(
            article, article_summary, content_grade, environment, source_evals
        )
        sections_to_edit = [s for s in assessment.sections if s.action == "EDIT"]
        thought = (
            f"{assessment.importance.tier} article — {assessment.article_class}. "
            f"Editing {len(sections_to_edit)} sections. "
            f"Effort: {assessment.effort_ceiling}."
        )
        yield _think("ASSESS", thought)
        yield ProgressEvent(
            stage="ASSESS", status="done",
            message=f"{assessment.importance.tier} | {assessment.article_class} | "
                    f"{len(sections_to_edit)} sections to edit | {assessment.effort_ceiling} effort",
            data={"assessment": assessment.model_dump()},
        )

        if not sections_to_edit:
            yield ProgressEvent(
                stage="ASSESS", status="error",
                message="Nothing to edit — assessment found no sections worth improving.",
            )
            return

        # ── PLAN → VALIDATE → EXECUTE → CRITIQUE loop ─────────────────────────
        all_section_drafts: list[SectionDraft] = []
        all_section_research: list[SectionResearch] = []
        final_critique: CritiqueResult | None = None
        assembled: str = ""

        for cycle in range(3):  # max 2 revision cycles (0, 1, 2 → PARTIAL_ACCEPT on 2)
            critique_for_planner = final_critique if cycle > 0 else None

            # ── PLAN ────────────────────────────────────────────────────────
            cycle_label = f" (revision {cycle})" if cycle > 0 else ""
            yield ProgressEvent(
                stage="PLAN", status="running",
                message=f"Planning tasks{cycle_label}...",
            )
            nodes, narrative = await plan_edits(article.title, assessment, critique_for_planner)

            # Validate the plan
            approved, feedback = await validate_plan(article.title, assessment, nodes)
            if not approved and cycle == 0:
                yield _think("PLAN", f"Plan needs revision: {feedback}")
                # One retry with feedback appended
                from workers.edit_planner import _revision_context
                if critique_for_planner is None:
                    from models import CritiqueResult as CR
                    feedback_critique = CR(
                        overall_verdict="REVISE",
                        revision_instructions=[feedback],
                    )
                else:
                    feedback_critique = critique_for_planner
                nodes, narrative = await plan_edits(
                    article.title, assessment, feedback_critique
                )

            dag_display = format_dag_for_display(nodes, narrative)
            yield _think("PLAN", dag_display)
            yield ProgressEvent(
                stage="PLAN", status="done",
                message=f"{len(nodes)} tasks planned{cycle_label}",
                data={
                    "dag": {nid: {"type": n.type, "params": n.params, "deps": n.deps}
                            for nid, n in nodes.items()},
                    "dag_narrative": narrative,
                },
            )

            # ── EXECUTE DAG ────────────────────────────────────────────────
            yield ProgressEvent(stage="EXEC", status="running", message="Executing task DAG...")

            ctx = {
                "article": article,
                "article_summary": article_summary,
                "source_evals": source_evals,
                "editor_norms": environment.editor_imposed_norms,
            }

            section_research_map: dict[str, SectionResearch] = {}
            section_draft_map: dict[str, SectionDraft] = {}
            synthesized: str = ""

            handlers = {
                "research_section": self._handle_research_section,
                "draft_section": self._handle_draft_section,
                "draft_full_article": self._handle_draft_full_article,
                "synthesize": self._handle_synthesize,
            }

            executor = DAGExecutor(handlers)
            async for dag_event in executor.run(nodes, ctx):
                if dag_event.status == "running":
                    yield _think("EXEC", dag_event.message)
                elif dag_event.status == "done":
                    node_id = dag_event.message.split(":")[0].strip()
                    node = nodes.get(node_id)
                    if node and node.result is not None:
                        if node.type == "research_section":
                            sr: SectionResearch = node.result
                            section_research_map[sr.section_name] = sr
                            n_claims = len([c for c in sr.claim_map.claims
                                           if c.status in ("uncited", "undercited")])
                            yield _think("EXEC", (
                                f"research_section({sr.section_name}): "
                                f"{n_claims} uncited claims, "
                                f"{len(sr.new_sources)} new sources found"
                            ))
                        elif node.type == "draft_section":
                            sd: SectionDraft = node.result
                            section_draft_map[sd.section_name] = sd
                            changes = sd.changes_made[:2] if sd.changes_made else ["revised"]
                            yield _think("EXEC", (
                                f"draft_section({sd.section_name}): "
                                + "; ".join(changes)
                            ))
                        elif node.type == "synthesize":
                            synthesized = node.result
                elif dag_event.status == "error":
                    yield _think("EXEC", f"⚠ {dag_event.message}")

            cycle_drafts = list(section_draft_map.values())
            assembled = synthesized or _assemble_with_drafts(article, cycle_drafts)

            if cycle == 0:
                all_section_drafts = cycle_drafts
                all_section_research = list(section_research_map.values())
            else:
                # Merge: update changed sections
                existing = {d.section_name: d for d in all_section_drafts}
                existing.update(section_draft_map)
                all_section_drafts = list(existing.values())

            yield ProgressEvent(
                stage="EXEC", status="done",
                message=f"{len(cycle_drafts)} sections drafted",
                data={"section_drafts": [d.model_dump() for d in all_section_drafts]},
            )

            # ── CRITIQUE ────────────────────────────────────────────────────
            yield ProgressEvent(stage="CRITIQUE", status="running", message="Critiquing each section...")

            source_report = _assemble_source_report(source_evals, [], all_section_research)

            section_critique_tasks = [
                critique_section(
                    article.title,
                    draft.section_name,
                    article.section_texts.get(draft.section_name, ""),
                    draft.revised_text,
                    source_report,
                )
                for draft in cycle_drafts
            ]
            section_critique_results: list[SectionCritiqueResult] = await asyncio.gather(
                *section_critique_tasks, return_exceptions=True
            )
            section_critique_results = [
                r for r in section_critique_results if isinstance(r, SectionCritiqueResult)
            ]

            for r in section_critique_results:
                icon = "✓" if r.verdict == "PASS" else "✗"
                yield _think("CRITIQUE", f"{icon} {r.section_name}: {r.verdict}")
                if r.issues:
                    yield _think("CRITIQUE", f"  Issues: {'; '.join(r.issues[:2])}")

            final_critique = await aggregate_critique(
                article.title, section_critique_results, cycle
            )

            yield ProgressEvent(
                stage="CRITIQUE", status="done",
                message=f"Verdict: {final_critique.overall_verdict}",
                data={"critique": final_critique.model_dump()},
            )

            verdict = final_critique.overall_verdict

            if verdict == "DISCARD":
                yield ProgressEvent(
                    stage="CRITIQUE", status="error",
                    message=f"Edit discarded: {final_critique.discard_reason}",
                )
                return

            if verdict in ("PASS", "PARTIAL_ACCEPT"):
                # On PARTIAL_ACCEPT: use passing sections only
                if verdict == "PARTIAL_ACCEPT" and final_critique.failing_sections:
                    yield _think("CRITIQUE", (
                        f"Partial accept: keeping {len(final_critique.passing_sections)} sections, "
                        f"reverting {len(final_critique.failing_sections)} to original"
                    ))
                    # Revert failing sections to original
                    filtered = [
                        d for d in all_section_drafts
                        if d.section_name in final_critique.passing_sections
                    ]
                    assembled = _assemble_with_drafts(article, filtered)
                    all_section_drafts = filtered
                break

            if cycle >= 2:
                # Exhausted revision budget → PARTIAL_ACCEPT
                final_critique.overall_verdict = "PARTIAL_ACCEPT"
                yield _think("CRITIQUE", "Revision budget exhausted — accepting passing sections.")
                filtered = [
                    d for d in all_section_drafts
                    if d.section_name in (final_critique.passing_sections or
                                         [d.section_name for d in all_section_drafts])
                ]
                assembled = _assemble_with_drafts(article, filtered)
                all_section_drafts = filtered
                break

            # REVISE: continue loop
            yield _think("CRITIQUE", (
                f"Revising {len(final_critique.failing_sections)} sections: "
                + ", ".join(final_critique.failing_sections)
            ))

        # ── GRADE OUTPUT ────────────────────────────────────────────────────
        yield ProgressEvent(stage="GRADE", status="running", message="Scoring the final output...")
        output_grade = await self.output_grader.run(assembled, article)
        quality_delta = output_grade.overall_score - content_grade.overall_score
        yield ProgressEvent(
            stage="GRADE", status="done",
            message=f"Output: {output_grade.letter_grade} (Δ {quality_delta:+.1f})",
        )

        # ── SUMMARIZE EDIT ────────────────────────────────────────────────
        yield ProgressEvent(stage="SUMMARIZE", status="running", message="Writing editorial summary...")
        edit_summary = await summarize_edit(article, assessment, all_section_drafts, final_critique)
        yield ProgressEvent(
            stage="SUMMARIZE", status="done",
            message="Editorial summary written",
        )

        # ── BUILD PROPOSAL ─────────────────────────────────────────────────
        original_text = "\n\n".join(article.section_texts.get(s, "") for s in article.sections)
        full_diff = _build_diff(original_text, assembled)

        all_new_sources = [s for sr in all_section_research for s in sr.new_sources]

        proposal = EditProposal(
            article=article,
            input_grade=content_grade,
            output_grade=output_grade,
            quality_delta=round(quality_delta, 2),
            editorial_environment=environment,
            assessment=assessment,
            source_audit=source_evals,
            new_sources=all_new_sources,
            section_drafts=all_section_drafts,
            critique=final_critique,
            edit_summary=edit_summary,
            full_diff=full_diff,
        )
        yield ProgressEvent(
            stage="GRADE", status="done",
            message="Edit proposal ready.",
            data={"proposal": proposal.model_dump()},
        )

    # ── DAG task handlers ─────────────────────────────────────────────────────

    async def _handle_research_section(
        self, params: dict, dep_results: dict, ctx: dict
    ) -> SectionResearch:
        section_name = params["section"]
        return await research_section(
            ctx["article"],
            section_name,
            ctx["article_summary"],
        )

    async def _handle_draft_section(
        self, params: dict, dep_results: dict, ctx: dict
    ) -> SectionDraft:
        section_name = params["section"]
        mode = params.get("mode", "CiteFix")
        article: WikiArticle = ctx["article"]
        article_summary: ArticleSummary = ctx["article_summary"]

        # Collect sources from research_section dependencies
        section_research_list: list[SectionResearch] = []
        audit: list[SourceEvaluation] = ctx.get("source_evals", [])

        for dep_id, dep_result in dep_results.items():
            if isinstance(dep_result, SectionResearch):
                section_research_list.append(dep_result)

        source_report = _assemble_source_report(audit, [], section_research_list)

        from models import SectionPlan
        section_plan = SectionPlan(
            name=section_name,
            modes=[mode],
            rationale=f"Mode: {mode}",
        )
        return await self.draft_writer.run(
            section_plan=section_plan,
            article=article,
            source_report=source_report,
            editor_norms=ctx.get("editor_norms", []),
        )

    async def _handle_draft_full_article(
        self, params: dict, dep_results: dict, ctx: dict
    ) -> str:
        """Full article rewrite — used when revision_scope=FULL_ARTICLE."""
        article: WikiArticle = ctx["article"]
        audit: list[SourceEvaluation] = ctx.get("source_evals", [])
        source_report = _assemble_source_report(audit, [], None)
        assembled = _assemble_with_drafts(article, [])
        return await self.synthesis_writer.run(article, [], source_report)

    async def _handle_synthesize(
        self, params: dict, dep_results: dict, ctx: dict
    ) -> str:
        article: WikiArticle = ctx["article"]
        audit: list[SourceEvaluation] = ctx.get("source_evals", [])

        # Collect all section drafts from dependencies
        drafts: list[SectionDraft] = []
        section_research_list: list[SectionResearch] = []
        for dep_result in dep_results.values():
            if isinstance(dep_result, SectionDraft):
                drafts.append(dep_result)
            elif isinstance(dep_result, SectionResearch):
                section_research_list.append(dep_result)

        source_report = _assemble_source_report(audit, [], section_research_list)
        return await self.synthesis_writer.run(article, drafts, source_report)
