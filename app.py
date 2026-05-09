# ABOUTME: Streamlit app — sidebar agent loop diagram, two-tab layout (Run/Debug).
# ABOUTME: Run tab shows per-stage collapsible thinking + inline results; Debug tab shows raw panels.

import asyncio

import plotly.graph_objects as go
import streamlit as st

from chart_utils import section_score_data, source_chart_data
from constants import STAGE_META
from dag_image import render_agent_loop, render_task_dag
from diff_utils import section_diff_html
from models import (
    ContentGrade, EditorialEnvironment, ArticleAssessment,
    CritiqueResult, EditProposal,
)
from orchestrator import WikiWriterOrchestrator

_PIPELINE_STAGES = ["FETCH", "GATHER", "ASSESS", "PLAN", "EXEC", "CRITIQUE", "GRADE", "SUMMARIZE"]

CAUTION_COLORS = {"LOW": "green", "MODERATE": "orange", "HIGH": "red", "CRITICAL": "red"}
VERDICT_COLORS = {
    "PASS": "#16A34A", "REVISE": "#D97706", "PARTIAL_ACCEPT": "#2563EB", "DISCARD": "#DC2626",
}


# ── Debug panel renderers ──────────────────────────────────────────────────────

def render_environment_panel(env: EditorialEnvironment) -> None:
    st.subheader("Editorial Environment")
    color = CAUTION_COLORS.get(env.caution_level, "gray")
    st.markdown(
        f"<span style='background:{color};color:white;padding:4px 10px;"
        f"border-radius:4px;font-weight:bold;'>{env.caution_level}</span>",
        unsafe_allow_html=True,
    )
    st.write("")
    col1, col2, col3 = st.columns(3)
    col1.metric("Revert Rate (12mo)", f"{env.revert_rate_12mo:.1%}")
    col2.metric("Edit Velocity", env.edit_velocity)
    col3.metric("Dominant Editor", env.dominant_editor or "None")
    if env.flip_flopped_sections:
        st.write("**Flip-flopped sections:**", ", ".join(env.flip_flopped_sections))
    if env.policies_and_restrictions:
        st.write("**Policies/restrictions:**")
        for p in env.policies_and_restrictions:
            st.write(f"- {p}")
    if env.editor_imposed_norms:
        st.write("**Editor norms:**")
        for n in env.editor_imposed_norms:
            st.write(f"- {n}")
    st.caption(env.environment_narrative)


def render_grade_panel(grade: ContentGrade) -> None:
    st.subheader("Article Quality")
    st.metric("Grade", f"{grade.letter_grade} ({grade.overall_score:.1f}/10)")
    rows = [{"Dimension": dim, "Score": f"{score:.1f}"} for dim, score in grade.dimension_scores.items()]
    st.table(rows)
    st.caption(grade.narrative)


def render_assessment_panel(assessment: ArticleAssessment) -> None:
    st.subheader("Article Assessment")
    col1, col2, col3 = st.columns(3)
    col1.metric("Importance", assessment.importance.tier)
    col2.metric("Class", assessment.article_class)
    col3.metric("Effort", assessment.effort_ceiling)
    st.caption(assessment.edit_rationale)
    if assessment.primary_weaknesses:
        st.write("**Primary weaknesses:**")
        for w in assessment.primary_weaknesses:
            st.write(f"- {w}")
    st.write("**Per-section decisions:**")
    for s in assessment.sections:
        icon = "✏️" if s.action == "EDIT" else "✓"
        tag = f"[{s.edit_type}]" if s.edit_type else ""
        st.write(f"{icon} **{s.name}** {tag} — {s.rationale}")


def render_section_diff(draft: dict) -> None:
    changes = draft.get("changes_made", [])
    header = f"**{draft['section_name']}**" + (f" — {changes[0]}" if changes else "")
    with st.expander(header, expanded=False):
        if changes:
            st.write("**Changes made:**")
            for c in changes:
                st.write(f"- {c}")
        orig, revised = draft["original_text"], draft["revised_text"]
        if orig.strip() == revised.strip():
            st.write("_(no text changes)_")
        else:
            st.html(section_diff_html(orig, revised))
        for label, cites in (
            ("Citations added", draft.get("citations_added", [])),
            ("Citations removed", draft.get("citations_removed", [])),
        ):
            if cites:
                st.write(f"**{label}:**", ", ".join(cites))


def render_diff_view(section_drafts: list) -> None:
    st.subheader("Section Drafts")
    if not section_drafts:
        st.write("No drafts available.")
        return
    for draft in section_drafts:
        render_section_diff(draft)


def render_critique_panel(critique: CritiqueResult) -> None:
    st.subheader("Critique")
    color = VERDICT_COLORS.get(critique.overall_verdict, "gray")
    st.markdown(
        f"<span style='background:{color};color:white;padding:4px 10px;"
        f"border-radius:4px;font-weight:bold;'>{critique.overall_verdict}</span>",
        unsafe_allow_html=True,
    )
    st.write("")
    if critique.section_results:
        for sec_name, sec_result in critique.section_results.items():
            icon = "✅" if sec_result.verdict == "PASS" else "❌"
            with st.expander(f"{icon} {sec_name}", expanded=sec_result.verdict == "FAIL"):
                for dim, data in sec_result.dimensions.items():
                    dim_icon = "✅" if data.verdict == "PASS" else "❌"
                    st.write(f"{dim_icon} **{dim}**: {data.notes}")
                if sec_result.suggested_fix:
                    st.info(f"Suggested fix: {sec_result.suggested_fix}")
    elif critique.dimension_results:
        for dim, result in critique.dimension_results.items():
            icon = "✅" if result.verdict == "PASS" else "❌"
            st.write(f"{icon} **{dim.replace('_', ' ').title()}**: {result.notes}")
    if critique.revision_instructions:
        st.write("**Revision instructions:**")
        for instr in critique.revision_instructions:
            st.write(f"- {instr}")
    if critique.discard_reason:
        st.error(f"Discard reason: {critique.discard_reason}")


def render_proposal_panel(proposal: EditProposal) -> None:
    st.subheader("Edit Proposal")
    col1, col2, col3 = st.columns(3)
    col1.metric("Input Grade",
                proposal.input_grade.letter_grade, f"{proposal.input_grade.overall_score:.1f}/10")
    col2.metric("Output Grade",
                proposal.output_grade.letter_grade, f"{proposal.output_grade.overall_score:.1f}/10")
    col3.metric("Quality Delta", f"{proposal.quality_delta:+.1f}", delta_color="normal")
    render_critique_panel(proposal.critique)
    if proposal.edit_summary:
        st.divider()
        st.subheader("Editorial Summary")
        st.write(proposal.edit_summary.narrative)
        st.divider()
        st.subheader("Submit to Wikipedia")
        st.text_area(
            "Edit summary (copy into Wikipedia's edit summary box)",
            proposal.edit_summary.disclosure_line,
            height=80,
        )
    col1, col2 = st.columns(2)
    if col1.button("✅ Approve edit", type="primary"):
        st.success("Approved. Copy the edit summary above and apply the diff to Wikipedia manually.")
    if col2.button("❌ Reject"):
        st.warning("Edit rejected.")


# ── Inline stage result renderers ─────────────────────────────────────────────

def render_source_charts(audit: list) -> None:
    status_counts, type_counts = source_chart_data(audit)
    col1, col2 = st.columns(2)
    with col1:
        fig = go.Figure(go.Pie(
            labels=list(status_counts.keys()),
            values=list(status_counts.values()),
            hole=0.3,
        ))
        fig.update_layout(title_text="Source Status", margin=dict(t=40, b=10, l=10, r=10),
                          height=220, showlegend=True)
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        fig = go.Figure(go.Pie(
            labels=list(type_counts.keys()),
            values=list(type_counts.values()),
            hole=0.3,
        ))
        fig.update_layout(title_text="Source Types", margin=dict(t=40, b=10, l=10, r=10),
                          height=220, showlegend=True)
        st.plotly_chart(fig, use_container_width=True)


def render_section_scores(section_grades: dict) -> None:
    sections, scores = section_score_data(section_grades)
    if not sections:
        return
    fig = go.Figure(go.Bar(
        x=scores, y=sections, orientation="h",
        marker_color=["#EF4444" if s < 5 else "#F59E0B" if s < 7 else "#22C55E" for s in scores],
    ))
    fig.update_layout(
        title_text="Score per Section", xaxis=dict(range=[0, 10]),
        margin=dict(t=40, b=10, l=10, r=10), height=max(120, len(sections) * 28),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_assessment_summary(assessment: ArticleAssessment) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Importance", assessment.importance.tier)
    col2.metric("Class", assessment.article_class)
    col3.metric("Effort", assessment.effort_ceiling)
    if assessment.primary_weaknesses:
        st.caption("**Weaknesses:** " + " · ".join(assessment.primary_weaknesses[:3]))
    editing = [s for s in assessment.sections if s.action == "EDIT"]
    skipped = [s for s in assessment.sections if s.action == "SKIP"]
    rows = [
        f"{'✏️' if s.action == 'EDIT' else '✓'} **{s.name}**"
        + (f" `{s.edit_type}`" if s.edit_type else "")
        + f" — {s.rationale}"
        for s in (editing + skipped)
    ]
    st.markdown("\n\n".join(rows))


def render_stage_results(stage: str, acc: dict) -> None:
    if stage == "GATHER":
        if "audit" in acc:
            render_source_charts(acc["audit"])
        if "grade" in acc:
            grade = ContentGrade.model_validate(acc["grade"])
            if grade.section_grades:
                render_section_scores(grade.section_grades)
    elif stage == "ASSESS" and "assessment" in acc:
        render_assessment_summary(ArticleAssessment.model_validate(acc["assessment"]))
    elif stage == "EXEC" and "section_drafts" in acc:
        render_diff_view(acc["section_drafts"])
    elif stage == "CRITIQUE" and "critique" in acc:
        render_critique_panel(CritiqueResult.model_validate(acc["critique"]))
    elif stage == "GRADE" and "proposal" in acc:
        render_proposal_panel(EditProposal.model_validate(acc["proposal"]))


# ── Live streaming runner ──────────────────────────────────────────────────────

def run_and_render(url: str) -> None:
    # ── Sidebar placeholders ───────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("#### Agent Loop")
        loop_ph = st.empty()
        st.markdown("---")
        st.markdown("#### Task DAG")
        dag_ph = st.empty()
        st.markdown("---")
        counter_ph = st.empty()

    # Render initial agent loop image (all pending)
    loop_ph.image(render_agent_loop([], None, set(), 0), width="stretch")

    # ── Main tabs ──────────────────────────────────────────────────────────────
    tab_run, tab_debug = st.tabs(["▶ Run", "🔬 Debug"])

    # Pre-allocate one placeholder per pipeline stage inside tab_run
    with tab_run:
        stage_phs = {stage: st.empty() for stage in _PIPELINE_STAGES}

    with tab_debug:
        debug_ph = st.empty()

    # ── Mutable state ──────────────────────────────────────────────────────────
    state = {
        "stage_history": [],
        "current_stage": None,
        "done_stages": set(),
        "loop_count": 0,
        "stage_thoughts": {s: [] for s in _PIPELINE_STAGES},
        "accumulated": {},
        "task_dag": {},
        "done_nodes": set(),
        "current_nodes": set(),
    }

    def _refresh_loop_image():
        png = render_agent_loop(
            state["stage_history"],
            state["current_stage"],
            state["done_stages"],
            state["loop_count"],
        )
        loop_ph.image(png, width="stretch")

    def _refresh_dag_image():
        if state["task_dag"]:
            png = render_task_dag(
                state["task_dag"],
                state["done_nodes"],
                state["current_nodes"],
            )
            dag_ph.image(png, width="stretch")

    def _refresh_stage_ph(stage: str):
        ph = stage_phs.get(stage)
        if ph is None:
            return
        thoughts = state["stage_thoughts"].get(stage, [])
        is_done = stage in state["done_stages"]
        _, running_label, done_label = STAGE_META.get(stage, ("•", stage, stage))

        with ph.container():
            if is_done:
                if thoughts:
                    with st.expander(f"💭 {done_label} — thinking (expand)", expanded=False):
                        st.markdown("\n\n".join(thoughts))
                render_stage_results(stage, state["accumulated"])
            else:
                st.markdown(f"⟳ **{running_label}**")
                if thoughts:
                    st.markdown("\n\n".join(thoughts))

    def _append_thought(stage: str, text: str):
        if stage not in state["stage_thoughts"]:
            state["stage_thoughts"][stage] = []
        state["stage_thoughts"][stage].append(text)
        _refresh_stage_ph(stage)

    def _render_debug(acc: dict) -> None:
        with debug_ph.container():
            if "grade" in acc and "environment" in acc:
                st.markdown("### Gather")
                col1, col2 = st.columns(2)
                with col1:
                    render_environment_panel(EditorialEnvironment.model_validate(acc["environment"]))
                with col2:
                    render_grade_panel(ContentGrade.model_validate(acc["grade"]))
                if "audit" in acc:
                    st.subheader("Sources")
                    stab1, stab2 = st.tabs(["Existing Citations", "New Sources"])
                    with stab1:
                        for s in acc["audit"]:
                            icon = "✅" if s["recommendation"] == "USE" else (
                                "⚠️" if s["recommendation"] == "WEAK" else "❌"
                            )
                            note = f" ({s['status']})" if s["status"] != "LIVE" else ""
                            st.write(
                                f"{icon} [{s['overall_score']:.1f}] `{s['domain_type']}`{note}"
                                f" — {s['url'][:80]}"
                            )
                            if s.get("topic_coverage_summary"):
                                st.caption(f"   {s['topic_coverage_summary']}")
                    with stab2:
                        new = acc.get("new_sources", [])
                        if not new:
                            st.write("_(none found)_")
                        for s in new:
                            st.write(
                                f"➕ [{s['overall_score']:.1f}] `{s['domain_type']}`"
                                f" — {s['url'][:80]}"
                            )
                            if s.get("topic_coverage_summary"):
                                st.caption(f"   {s['topic_coverage_summary']}")

            if "assessment" in acc:
                st.markdown("### Assess")
                render_assessment_panel(ArticleAssessment.model_validate(acc["assessment"]))

            if "dag" in acc and state["task_dag"]:
                st.markdown("### Plan")
                png = render_task_dag(state["task_dag"], set(), set())
                st.image(png, width="stretch")
                st.caption(acc.get("dag_narrative", ""))

            if "section_drafts" in acc:
                st.markdown("### Execute")
                render_diff_view(acc["section_drafts"])

            if "critique" in acc:
                st.markdown("### Critique")
                render_critique_panel(CritiqueResult.model_validate(acc["critique"]))

            if "proposal" in acc:
                st.markdown("### Grade")
                proposal = EditProposal.model_validate(acc["proposal"])
                col1, col2, col3 = st.columns(3)
                col1.metric("Input Grade",
                            proposal.input_grade.letter_grade,
                            f"{proposal.input_grade.overall_score:.1f}/10")
                col2.metric("Output Grade",
                            proposal.output_grade.letter_grade,
                            f"{proposal.output_grade.overall_score:.1f}/10")
                col3.metric("Quality Delta", f"{proposal.quality_delta:+.1f}", delta_color="normal")

    async def _stream():
        async for event in WikiWriterOrchestrator().run(url):
            stage = event.stage

            # Stage transition bookkeeping — only on non-thinking events so that
            # narrator thoughts (emitted with lowercase stage names) don't corrupt
            # the canonical uppercase stage state used for the agent loop image.
            if event.status != "thinking" and stage != state["current_stage"]:
                if stage in state["done_stages"]:
                    state["loop_count"] += 1
                state["current_stage"] = stage
                state["stage_history"].append(stage)
                _refresh_loop_image()

            if event.status == "thinking":
                # Use the already-set current_stage for separator labels so we get
                # the friendly STAGE_META label regardless of narrator's stage name.
                _append_thought(state["current_stage"] or stage, f"*{event.message}*")

            elif event.status == "running":
                if event.count is not None and event.total is not None:
                    counter_ph.markdown(
                        f"**{event.message}:** {event.count} / {event.total}"
                    )
                # Track in-flight DAG node
                if stage == "EXEC" and event.message and ":" in event.message:
                    node_id = event.message.split(":")[0].strip()
                    if node_id in state["task_dag"]:
                        state["current_nodes"].add(node_id)
                        _refresh_dag_image()

            elif event.status == "done":
                state["done_stages"].add(stage)
                counter_ph.empty()

                if event.data:
                    state["accumulated"].update(event.data)
                    if "dag" in event.data:
                        state["task_dag"] = event.data["dag"]
                        state["done_nodes"].clear()
                        state["current_nodes"].clear()
                        _refresh_dag_image()

                # Mark DAG node done during EXEC
                if stage == "EXEC" and event.message and ":" in event.message:
                    node_id = event.message.split(":")[0].strip()
                    if node_id in state["task_dag"]:
                        state["current_nodes"].discard(node_id)
                        state["done_nodes"].add(node_id)
                        _refresh_dag_image()

                _refresh_loop_image()
                _refresh_stage_ph(stage)
                _render_debug(state["accumulated"])

            elif event.status == "error":
                _append_thought(stage, f"❌ **{event.message}**")
                _refresh_loop_image()

    asyncio.run(_stream())


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(page_title="WikiWriter", layout="wide")

    with st.sidebar:
        st.title("WikiWriter")
        st.caption("Quality-first Wikipedia editing agent")

    url = st.text_input(
        "Wikipedia article URL",
        placeholder="https://en.wikipedia.org/wiki/Super_Bowl_XXV",
    )
    analyse = st.button("Analyse & draft edit", type="primary")

    if not analyse or not url:
        return

    run_and_render(url)


if __name__ == "__main__":
    main()
