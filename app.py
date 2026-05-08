# ABOUTME: Streamlit app — live per-stage progress with inline thinking and progressive panel rendering.
# ABOUTME: Results (environment, grade, assessment, DAG, diffs, critique) appear as each stage completes.

import asyncio
import io

import streamlit as st
from PIL import Image, ImageDraw, ImageFont

from constants import STAGE_META
from dag import dag_layers
from diff_utils import section_diff_html
from models import (
    ContentGrade, EditorialEnvironment, ArticleAssessment,
    CritiqueResult, EditProposal,
)
from orchestrator import WikiWriterOrchestrator

CAUTION_COLORS = {"LOW": "green", "MODERATE": "orange", "HIGH": "red", "CRITICAL": "red"}
VERDICT_COLORS = {
    "PASS": "#16A34A", "REVISE": "#D97706", "PARTIAL_ACCEPT": "#2563EB", "DISCARD": "#DC2626",
}
CLAIM_ICONS = {"cited": "✅", "undercited": "⚠️", "uncited": "❌", "consensus-uncited": "ℹ️"}


# ── DAG image renderer ─────────────────────────────────────────────────────────

_TYPE_COLORS = {
    "research_section":   ("#DBEAFE", "#3B82F6"),   # blue
    "draft_section":      ("#DCFCE7", "#16A34A"),   # green
    "synthesize":         ("#F3E8FF", "#9333EA"),   # purple
    "draft_full_article": ("#FEF9C3", "#CA8A04"),   # amber
}
_DEFAULT_NODE_COLOR = ("#F1F5F9", "#64748B")


def _dag_png(dag: dict) -> bytes:
    """Render DAG as a PNG image (bytes). Nodes are colour-coded by type, layers flow left→right."""
    layers = dag_layers(dag)

    NW, NH = 230, 66    # node width / height (px)
    HG, VG = 72, 14     # horizontal / vertical gap between nodes
    PAD = 40            # canvas padding

    n_layers = len(layers)
    max_per_layer = max(len(layer) for layer in layers)

    W = n_layers * NW + (n_layers - 1) * HG + 2 * PAD
    H = max(160, max_per_layer * NH + (max_per_layer - 1) * VG + 2 * PAD)

    # Compute pixel centres for every node
    pos: dict[str, tuple[int, int]] = {}
    for li, layer in enumerate(layers):
        n = len(layer)
        col_h = n * NH + (n - 1) * VG
        y0 = (H - col_h) // 2
        for i, nid in enumerate(layer):
            cx = PAD + li * (NW + HG) + NW // 2
            cy = y0 + i * (NH + VG) + NH // 2
            pos[nid] = (cx, cy)

    img = Image.new("RGB", (W, H), "#F8FAFC")
    draw = ImageDraw.Draw(img)

    try:
        f_label = ImageFont.load_default(size=13)
        f_small = ImageFont.load_default(size=11)
        f_id = ImageFont.load_default(size=10)
    except TypeError:                          # older Pillow fallback
        f_label = f_small = f_id = ImageFont.load_default()

    # Edges (drawn first so nodes appear on top)
    for nid, node in dag.items():
        cx2, cy2 = pos[nid]
        for dep in node.get("deps", []):
            cx1, cy1 = pos[dep]
            x_start = cx1 + NW // 2
            x_end = cx2 - NW // 2 - 1
            # Horizontal line from right edge → arrow tip
            draw.line([(x_start, cy1), (x_end - 4, cy2)], fill="#94A3B8", width=2)
            # Arrowhead
            draw.polygon(
                [(x_end - 9, cy2 - 5), (x_end - 9, cy2 + 5), (x_end, cy2)],
                fill="#94A3B8",
            )

    # Nodes
    for nid, node in dag.items():
        cx, cy = pos[nid]
        x0, y0 = cx - NW // 2 + 1, cy - NH // 2 + 1
        x1, y1 = cx + NW // 2 - 1, cy + NH // 2 - 1

        fill, border = _TYPE_COLORS.get(node.get("type", ""), _DEFAULT_NODE_COLOR)
        draw.rounded_rectangle([x0, y0, x1, y1], radius=8, fill=fill, outline=border, width=2)

        # Small ID badge in top-left corner
        draw.text((x0 + 7, y0 + 5), f"[{nid}]", fill=border, font=f_id)

        # Type name centred vertically (slight upward shift when params present)
        params = node.get("params", {})
        type_label = node.get("type", "").replace("_", " ")
        has_params = bool(params)
        draw.text(
            (cx, cy - 7 if has_params else cy),
            type_label,
            fill="#1E293B",
            anchor="mm",
            font=f_label,
        )

        # Params line beneath the type label
        if has_params:
            pstr = "  ".join(str(v) for v in params.values())
            if len(pstr) > 30:
                pstr = pstr[:28] + "…"
            draw.text((cx, cy + 10), pstr, fill="#475569", anchor="mm", font=f_small)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Panel renderers ────────────────────────────────────────────────────────────

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


def render_dag_panel(dag: dict, narrative: str) -> None:
    st.subheader("Task DAG")
    if not dag:
        st.write("_(empty plan)_")
        return
    png = _dag_png(dag)
    st.image(png, use_container_width=True)
    st.caption(narrative)


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


def render_diff_view(section_drafts: list[dict]) -> None:
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


# ── Live streaming runner ──────────────────────────────────────────────────────

def run_and_render(url: str) -> None:
    stage_widgets: dict[str, object] = {}
    accumulated: dict = {}
    prev_stage: list[str] = []

    async def stream():
        async for event in WikiWriterOrchestrator().run(url):
            stage = event.stage
            icon, running_label, done_label = STAGE_META.get(stage, ("•", stage, stage))

            if stage not in stage_widgets:
                stage_widgets[stage] = st.status(f"{icon} {running_label}", expanded=True)
            widget = stage_widgets[stage]

            if event.status == "thinking":
                widget.markdown(f"*{event.message}*")
            elif event.status == "running":
                if "/" in event.message:
                    widget.update(label=f"{icon} {event.message}")
                else:
                    widget.markdown(event.message)
            elif event.status == "done":
                if prev_stage:
                    stage_widgets[prev_stage[0]].update(expanded=False)
                widget.update(
                    label=f"{icon} {done_label} — {event.message}",
                    state="complete", expanded=True,
                )
                prev_stage[:] = [stage]
                if event.data:
                    accumulated.update(event.data)
                _render_inline(event, accumulated)
            elif event.status == "error":
                widget.update(label=f"{icon} {event.message}", state="error", expanded=True)

    asyncio.run(stream())


def _render_inline(event, accumulated: dict) -> None:
    if event.stage == "GATHER" and "grade" in accumulated and "environment" in accumulated:
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            render_environment_panel(EditorialEnvironment.model_validate(accumulated["environment"]))
        with col2:
            render_grade_panel(ContentGrade.model_validate(accumulated["grade"]))
        if "audit" in accumulated:
            st.subheader("Sources")
            tab1, tab2 = st.tabs(["Existing Citations", "New Sources"])
            with tab1:
                for s in accumulated["audit"]:
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
            with tab2:
                new = accumulated.get("new_sources", [])
                if not new:
                    st.write("_(none found)_")
                for s in new:
                    st.write(f"➕ [{s['overall_score']:.1f}] `{s['domain_type']}` — {s['url'][:80]}")
                    if s.get("topic_coverage_summary"):
                        st.caption(f"   {s['topic_coverage_summary']}")

    elif event.stage == "ASSESS" and "assessment" in accumulated:
        st.divider()
        render_assessment_panel(ArticleAssessment.model_validate(accumulated["assessment"]))

    elif event.stage == "PLAN" and "dag" in accumulated:
        st.divider()
        render_dag_panel(accumulated["dag"], accumulated.get("dag_narrative", ""))

    elif event.stage == "EXEC" and "section_drafts" in accumulated:
        st.divider()
        render_diff_view(accumulated["section_drafts"])

    elif event.stage == "CRITIQUE" and "critique" in accumulated:
        st.divider()
        render_critique_panel(CritiqueResult.model_validate(accumulated["critique"]))

    elif event.stage == "GRADE" and "proposal" in accumulated:
        st.divider()
        render_proposal_panel(EditProposal.model_validate(accumulated["proposal"]))


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(page_title="WikiWriter", layout="wide")
    st.title("WikiWriter")
    st.caption("Quality-first Wikipedia editing agent")

    url = st.text_input(
        "Wikipedia article URL",
        placeholder="https://en.wikipedia.org/wiki/Service_star",
    )
    analyse = st.button("Analyse & draft edit", type="primary")

    if not analyse or not url:
        return

    run_and_render(url)


if __name__ == "__main__":
    main()
