# ABOUTME: DAG-based orchestrator — assess WHAT, plan HOW, execute DAG, critique, revise.
# ABOUTME: Emits ProgressEvents as async generator; writes verbose per-run log to logs/.

import asyncio
import json
import os
import re
from datetime import datetime, timezone

from cache import get_cache_stats, reset_cache_stats, get_telemetry, reset_telemetry
from dag import DAGExecutor
from utils.log import set_log_sink, log_stage_event, log_run_header, close_log_sink
from models import (
    ProgressEvent, WikiArticle, SourceEvaluation,
    SectionResearch, SectionDraft,
    CritiqueResult, SectionCritiqueResult, EditProposal, ContentGrade,
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
from workers.stage_summarizer import summarize_stage


def _grade_regression_critique(
    input_grade: "ContentGrade",
    output_grade: "ContentGrade",
) -> "CritiqueResult":
    """Build a CritiqueResult from a negative quality delta to drive a re-plan."""
    delta = output_grade.overall_score - input_grade.overall_score
    return CritiqueResult(
        overall_verdict="REVISE",
        revision_scope="FULL_ARTICLE",
        revision_instructions=[
            f"Quality dropped by {abs(delta):.1f} points "
            f"({input_grade.overall_score:.1f} → {output_grade.overall_score:.1f}). "
            "The edits made things worse, not better.",
            "Re-plan from scratch: choose different sections or a different approach.",
            "Do not repeat the same edits that caused the regression.",
        ],
    )


def _inject_revision_notes(
    nodes: dict,
    critique: "CritiqueResult | None",
) -> None:
    """Inject critic suggested_fix into draft_section node params for revision cycles."""
    if critique is None:
        return
    for node in nodes.values():
        if node.type != "draft_section":
            continue
        section = node.params.get("section")
        sr = critique.section_results.get(section)
        if sr and sr.suggested_fix:
            node.params["revision_notes"] = sr.suggested_fix


def _think(stage: str, message: str) -> ProgressEvent:
    return ProgressEvent(stage=stage, status="thinking", message=message)


async def _narrate(stage: str, context: dict):
    """Yield a stream of thinking ProgressEvents from the narrator, line by line."""
    async for thought in narrate(stage, context):
        yield _think(stage, thought)


async def _emit_summary(stage: str, context: dict):
    """Yield a summary ProgressEvent for the completed stage."""
    text = await summarize_stage(stage, context)
    if text:
        yield ProgressEvent(stage=stage, status="summary", message=text)


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

        set_log_sink(f"logs/{ts}_{slug}.log")
        log_run_header(url, start.isoformat())

        with open(f"logs/{ts}_{slug}.jsonl", "w") as log:
            def _write(entry: dict) -> None:
                log.write(json.dumps(entry) + "\n")
                log.flush()

            _write({"type": "run_start", "url": url, "started_at": start.isoformat()})
            reset_telemetry()

            seen_stages: set[str] = set()
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

                if event.status == "running" and event.stage not in seen_stages:
                    seen_stages.add(event.stage)
                    log_stage_event(event.stage, "STAGE_START")
                elif event.status == "done" and event.stage in seen_stages:
                    log_stage_event(event.stage, "STAGE_DONE", event.message or "")
                elif event.status == "thinking":
                    log_stage_event(event.stage, "THINK", event.message or "")
                elif event.status == "summary":
                    log_stage_event(event.stage, "SUMMARY", event.message or "")
                elif event.status == "error":
                    log_stage_event(event.stage, "ERROR", event.message or "")

                yield event

            _write({
                "type": "run_end",
                "t": round((datetime.now(timezone.utc) - start).total_seconds(), 2),
                "cache": get_cache_stats(),
                "telemetry": get_telemetry(),
            })

        close_log_sink()

    async def _run(self, url: str):
        # ── FETCH ─────────────────────────────────────────────────────────────
        yield ProgressEvent(stage="FETCH", status="running", message=f"Fetching {url}...")
        article = await fetch_article(url)
        lead_text = article.section_texts.get("Lead", "")
        async for t in _narrate("fetch", {
            "article_title": article.title,
            "assessment_class": article.assessment_class or "unrated",
            "n_sections": len(article.sections),
            "n_citations": len(article.citations),
            "sections": article.sections[:12],
            "intro_text": lead_text,
        }):
            yield t
        async for s in _emit_summary("fetch", {
            "article_title": article.title,
            "assessment_class": article.assessment_class or "unrated",
            "n_sections": len(article.sections),
            "n_citations": len(article.citations),
            "sections": article.sections[:12],
            "intro_text": lead_text,
        }):
            yield s
        yield ProgressEvent(
            stage="FETCH", status="done",
            message=(
                f"'{article.title}' — {len(article.sections)} sections,"
                f" {len(article.citations)} citations"
            ),
        )

        # ── GATHER EVIDENCE (parallel) ────────────────────────────────────────
        yield ProgressEvent(stage="GATHER", status="running", message="Gathering evidence in parallel...")

        # summarize_article must run first
        article_summary = await summarize_article(article)

        # Now all parallel tasks
        n_cit = min(len(article.citations), 20)
        yield _think("GATHER", f"Checking {n_cit} citations, grading content, reading talk page...")

        _source_sem = asyncio.Semaphore(5)

        async def _eval_source(citation):
            async with _source_sem:
                return await self.source_evaluator.evaluate(citation.url, article_summary)

        citations_to_eval = article.citations[:20]
        grade_task = asyncio.create_task(self.grader.run(article))
        env_task = asyncio.create_task(self.env_analyzer.run(article))
        source_tasks = [
            asyncio.create_task(_eval_source(c))
            for c in citations_to_eval
        ]

        content_grade, environment = await asyncio.gather(grade_task, env_task)

        source_results = []
        for i, task in enumerate(asyncio.as_completed(source_tasks), start=1):
            result = await task
            source_results.append(result)
            yield ProgressEvent(
                stage="GATHER", status="running",
                message="Evaluating sources",
                count=i, total=len(citations_to_eval),
            )
        source_evals = [r for r in source_results if isinstance(r, SourceEvaluation)]

        n_usable = sum(1 for s in source_evals if s.recommendation == "USE")
        n_dead = sum(1 for s in source_evals if s.status == "DEAD")

        async for t in _narrate("gather", {
            "article_title": article.title,
            "article_topic": article_summary.topic,
            "article_scope": article_summary.scope,
            "grade": content_grade.letter_grade,
            "score": content_grade.overall_score,
            "dimension_scores": content_grade.dimension_scores,
            "caution_level": environment.caution_level,
            "revert_rate": environment.revert_rate_12mo,
            "flip_flopped_sections": environment.flip_flopped_sections,
            "active_disputes": environment.active_disputes,
            "resolved_disputes": environment.resolved_disputes,
            "active_topics": environment.active_topics,
            "wikiproject_affiliations": environment.wikiproject_affiliations,
            "environment_narrative": environment.environment_narrative,
            "policies": environment.policies_and_restrictions,
            "n_sources_usable": n_usable,
            "n_sources_dead": n_dead,
            "n_sources_total": len(source_evals),
        }):
            yield t

        async for s in _emit_summary("gather", {
            "article_title": article.title,
            "grade": content_grade.letter_grade,
            "score": content_grade.overall_score,
            "dimension_scores": content_grade.dimension_scores,
            "caution_level": environment.caution_level,
            "n_sources_usable": n_usable,
            "n_sources_dead": n_dead,
            "n_sources_total": len(source_evals),
            "flip_flopped_sections": environment.flip_flopped_sections,
            "active_disputes": environment.active_disputes,
        }):
            yield s
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

        # ── ASSESS (WHAT) — may loop through FOCUS for large articles ─────────
        yield ProgressEvent(stage="ASSESS", status="running", message="Assessing what the article needs...")
        assessment = await assess_article(
            article, article_summary, content_grade, environment, source_evals
        )

        if assessment.needs_focus and not assessment.no_edit:
            candidate_names = [s.name for s in assessment.sections if s.action == "EDIT"]
            yield ProgressEvent(
                stage="ASSESS", status="done",
                message=(
                    f"Pass 1 complete — {len(candidate_names)} candidates identified,"
                    " reading section text…"
                ),
                data={"assessment": assessment.model_dump()},
            )

            # ── FOCUS ────────────────────────────────────────────────────────
            yield ProgressEvent(
                stage="FOCUS", status="running",
                message=f"Reading {len(candidate_names)} candidate sections…",
            )
            focus_context = {"candidate_sections": candidate_names}
            yield ProgressEvent(
                stage="FOCUS", status="done",
                message=f"Section text loaded for: {', '.join(candidate_names)}",
            )

            # ── ASSESS Pass 2 ────────────────────────────────────────────────
            yield ProgressEvent(
                stage="ASSESS", status="running",
                message="Final section selection with full text context…",
            )
            assessment = await assess_article(
                article, article_summary, content_grade, environment, source_evals,
                focus_context=focus_context,
            )

        sections_to_edit = [s for s in assessment.sections if s.action == "EDIT"]
        assess_ctx = {
            "article_title": article.title,
            "importance": assessment.importance.tier,
            "article_class": assessment.article_class,
            "effort_ceiling": assessment.effort_ceiling,
            "edit_rationale": assessment.edit_rationale,
            "no_edit": assessment.no_edit,
            "no_edit_reason": assessment.no_edit_reason,
            "primary_weaknesses": assessment.primary_weaknesses,
            "source_trust_verdict": assessment.source_trust_verdict,
            "sections_to_edit": [
                {"name": s.name, "edit_type": s.edit_type, "rationale": s.rationale}
                for s in sections_to_edit
            ],
            "would_edit_sections": [
                {"name": s.name, "edit_type": s.edit_type, "rationale": s.rationale}
                for s in assessment.would_edit_sections
            ],
        }
        async for t in _narrate("assess", assess_ctx):
            yield t
        async for s in _emit_summary("assess", assess_ctx):
            yield s

        if assessment.no_edit:
            yield ProgressEvent(
                stage="ASSESS", status="done",
                message=f"No edit — {assessment.no_edit_reason}",
                data={"assessment": assessment.model_dump()},
            )
            return

        yield ProgressEvent(
            stage="ASSESS", status="done",
            message=f"{assessment.importance.tier} | {assessment.article_class} | "
                    f"{len(sections_to_edit)} sections to edit | {assessment.effort_ceiling} effort",
            data={"assessment": assessment.model_dump()},
        )

        if not sections_to_edit:
            yield ProgressEvent(
                stage="ASSESS", status="done",
                message="Assessment complete — no sections flagged for editing.",
                data={"assessment": assessment.model_dump()},
            )
            return

        # ── PLAN → VALIDATE → EXECUTE → CRITIQUE → GRADE loop ────────────────
        # Outer loop: retry the full plan if grading shows a quality regression.
        # Inner loop: revision cycles driven by critique verdict.
        output_grade = None
        grade_regression_critique: CritiqueResult | None = None

        for grade_cycle in range(2):  # at most one re-plan after grade regression
            all_section_drafts = []
            all_section_research = []
            final_critique = grade_regression_critique  # None on first outer pass
            assembled = ""

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
                    yield _think("PLAN", f"Validator flagged this plan: {feedback}")
                    # One retry with feedback appended
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

                if cycle > 0:
                    _inject_revision_notes(nodes, final_critique)

                dag_display = format_dag_for_display(nodes, narrative)
                yield _think("PLAN", dag_display)
                async for t in _narrate("plan", {
                    "article_title": article.title,
                    "cycle": cycle,
                    "n_tasks": len(nodes),
                    "narrative": narrative,
                    "tasks": [
                        {"id": nid, "type": n.type, "params": n.params}
                        for nid, n in nodes.items()
                    ],
                }):
                    yield t
                async for s in _emit_summary("plan", {
                    "article_title": article.title,
                    "cycle": cycle,
                    "n_tasks": len(nodes),
                    "narrative": narrative,
                    "tasks": [
                        {"id": nid, "type": n.type, "params": n.params}
                        for nid, n in nodes.items()
                    ],
                }):
                    yield s
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
                                async for t in _narrate("exec_research", {
                                    "section": sr.section_name,
                                    "n_uncited_claims": n_claims,
                                    "uncited_claims": [
                                        c.text[:120] for c in sr.claim_map.claims
                                        if c.status in ("uncited", "undercited")
                                    ][:4],
                                    "n_new_sources": len(sr.new_sources),
                                    "new_source_summaries": [
                                        s.topic_coverage_summary for s in sr.new_sources[:3]
                                    ],
                                }):
                                    yield t
                            elif node.type == "draft_section":
                                sd: SectionDraft = node.result
                                section_draft_map[sd.section_name] = sd
                                async for t in _narrate("exec_draft", {
                                    "section": sd.section_name,
                                    "changes_made": sd.changes_made[:4],
                                    "citations_added": sd.citations_added[:3],
                                    "citations_removed": sd.citations_removed[:3],
                                    "text_changed": sd.original_text.strip() != sd.revised_text.strip(),
                                }):
                                    yield t
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

                async for s in _emit_summary("exec", {
                    "article_title": article.title,
                    "cycle": cycle,
                    "n_sections_drafted": len(cycle_drafts),
                    "sections": [
                        {
                            "name": d.section_name,
                            "changes": d.changes_made[:3],
                            "citations_added": len(d.citations_added),
                            "citations_removed": len(d.citations_removed),
                        }
                        for d in cycle_drafts
                    ],
                }):
                    yield s
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

                final_critique = await aggregate_critique(
                    article.title, section_critique_results, cycle
                )

                async for t in _narrate("critique", {
                    "article_title": article.title,
                    "cycle": cycle,
                    "overall_verdict": final_critique.overall_verdict,
                    "passing_sections": final_critique.passing_sections,
                    "failing_sections": final_critique.failing_sections,
                    "section_issues": {
                        r.section_name: r.issues[:2]
                        for r in section_critique_results if r.issues
                    },
                    "revision_instructions": final_critique.revision_instructions[:3],
                }):
                    yield t

                async for s in _emit_summary("critique", {
                    "article_title": article.title,
                    "cycle": cycle,
                    "overall_verdict": final_critique.overall_verdict,
                    "passing_sections": final_critique.passing_sections,
                    "failing_sections": final_critique.failing_sections,
                    "revision_instructions": final_critique.revision_instructions[:3],
                }):
                    yield s
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
                        yield _think(
                            "CRITIQUE",
                            f"Keeping {len(final_critique.passing_sections)} sections, "
                            f"reverting {len(final_critique.failing_sections)} that didn't pass.",
                        )
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
                        if d.section_name in (
                            final_critique.passing_sections or
                            [d.section_name for d in all_section_drafts]
                        )
                    ]
                    assembled = _assemble_with_drafts(article, filtered)
                    all_section_drafts = filtered
                    break

                # REVISE: continue loop
                yield _think("CRITIQUE", (
                    f"Revising {len(final_critique.failing_sections)} sections: "
                    + ", ".join(final_critique.failing_sections)
                ))

            # ── GRADE OUTPUT ─────────────────────────────────────────────────
            yield ProgressEvent(stage="GRADE", status="running", message="Scoring the final output...")
            output_grade = await self.output_grader.run(assembled, article)
            quality_delta = output_grade.overall_score - content_grade.overall_score
            async for s in _emit_summary("grade", {
                "article_title": article.title,
                "input_grade": content_grade.letter_grade,
                "input_score": content_grade.overall_score,
                "output_grade": output_grade.letter_grade,
                "output_score": output_grade.overall_score,
                "quality_delta": quality_delta,
            }):
                yield s
            yield ProgressEvent(
                stage="GRADE", status="done",
                message=f"Output: {output_grade.letter_grade} (Δ {quality_delta:+.1f})",
            )

            if quality_delta < 0 and grade_cycle == 0:
                grade_regression_critique = _grade_regression_critique(content_grade, output_grade)
                yield _think(
                    "GRADE",
                    f"Quality regressed by {abs(quality_delta):.1f} points — re-planning from scratch.",
                )
                continue  # outer grade_cycle loop: retry with regression critique
            break  # satisfied: no regression, or already on final attempt

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

        # ── OUTPUT ───────────────────────────────────────────────────────────
        yield ProgressEvent(stage="OUTPUT", status="running", message="Preparing final output...")
        yield ProgressEvent(
            stage="OUTPUT", status="done",
            message=f"{len(all_section_drafts)} section(s) changed",
            data={"assembled_wikitext": assembled},
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

        # Collect sources from research_section dependencies
        section_research_list: list[SectionResearch] = []
        audit: list[SourceEvaluation] = ctx.get("source_evals", [])

        for dep_id, dep_result in dep_results.items():
            if isinstance(dep_result, SectionResearch):
                section_research_list.append(dep_result)

        source_report = _assemble_source_report(audit, [], section_research_list)

        from models import SectionPlan
        revision_notes = params.get("revision_notes", "")
        rationale = f"Mode: {mode}"
        if revision_notes:
            rationale += f"\nRevision notes from critic: {revision_notes}"
        section_plan = SectionPlan(
            name=section_name,
            modes=[mode],
            rationale=rationale,
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
