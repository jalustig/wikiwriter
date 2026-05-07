# ABOUTME: Streamlit app — live per-stage progress with inline thinking and progressive panel rendering.
# ABOUTME: Results (risk, grade, plan, diff) appear as soon as each stage completes.

import asyncio
import difflib
import re

import plotly.graph_objects as go
import streamlit as st

from models import (
    WikiArticle, ContentGrade, EditorialRiskProfile,
    ImprovementPlan, ClaimMap, CritiqueResult, EditProposal,
)
from orchestrator import WikiWriterOrchestrator

STATUS_COLORS = {
    "editing":  "#2196F3",
    "excluded": "#F44336",
    "ok":       "#4CAF50",
}

MODE_SHORT = {
    "Citation Repair":          "Cite Fix",
    "Claim Attribution":        "Cite Add",
    "Section Expansion":        "Expand",
    "Section Rewrite":          "Rewrite",
    "Contradiction Integration": "Contradict",
    "Synthesis Pass":           "Synthesis",
}

STAGE_META = {
    "FETCH":    ("🌐", "Reading article…",        "Read article"),
    "INTAKE":   ("📊", "Assessing quality…",       "Quality assessed"),
    "PLAN":     ("🗺️",  "Planning edits…",          "Edit plan ready"),
    "CLAIMS":   ("🔎", "Tagging claims…",          "Claims tagged"),
    "SOURCES":  ("🔍", "Evaluating sources…",      "Sources evaluated"),
    "DRAFT":    ("✏️",  "Writing drafts…",          "Drafts written"),
    "CRITIQUE": ("🔬", "Reviewing draft…",         "Draft reviewed"),
    "GRADE":    ("📈", "Scoring output…",          "Output scored"),
}

RISK_COLORS = {"LOW": "green", "MODERATE": "orange", "HIGH": "red", "CRITICAL": "red"}
VERDICT_COLORS = {"PASS": "green", "REVISE": "orange", "DISCARD": "red"}
CLAIM_ICONS = {"cited": "✅", "undercited": "⚠️", "uncited": "❌", "consensus-uncited": "ℹ️"}

_DIFF_CSS = """
<style>
table.diff {
    font-family: ui-monospace, monospace;
    font-size: 13px;
    border-collapse: collapse;
    width: 100%;
    table-layout: fixed;
}
table.diff td, table.diff th {
    padding: 3px 8px;
    vertical-align: top;
    word-break: break-word;
    white-space: pre-wrap;
    border: 1px solid #e0e0e0;
}
table.diff .diff_header { background: #f6f8fa; color: #555; font-size: 11px; width: 3em; }
table.diff .diff_next   { background: #f6f8fa; width: 1.5em; }
table.diff td.diff_add  { background: #e6ffec; }
table.diff td.diff_chg  { background: #fff8c5; }
table.diff td.diff_sub  { background: #ffeef0; }
table.diff span.diff_add { background: #acf2bd; }
table.diff span.diff_chg { background: #ffd33d; }
table.diff span.diff_sub { background: #fdb8c0; text-decoration: line-through; }
col.diff_header { width: 3em; }
col.diff_next   { width: 1.5em; }
</style>
"""


def _split_sentences(text: str) -> list[str]:
    """Split prose into sentence-level units so diffs are meaningful."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def _html_diff(original: str, revised: str) -> str:
    """Return side-by-side HTML diff table at sentence granularity."""
    orig_lines = _split_sentences(original)
    rev_lines = _split_sentences(revised)
    d = difflib.HtmlDiff(wrapcolumn=72)
    return _DIFF_CSS + d.make_table(
        orig_lines, rev_lines,
        fromdesc="Original", todesc="Revised",
        context=True, numlines=2,
    )


# ── Panel renderers ────────────────────────────────────────────────────────────

def render_risk_panel(risk: EditorialRiskProfile) -> None:
    st.subheader("Editorial Risk")
    color = RISK_COLORS.get(risk.risk_tier, "gray")
    st.markdown(
        f"<span style='background:{color};color:white;padding:4px 10px;"
        f"border-radius:4px;font-weight:bold;'>{risk.risk_tier}</span>",
        unsafe_allow_html=True,
    )
    st.write("")
    col1, col2, col3 = st.columns(3)
    col1.metric("Revert Rate (12mo)", f"{risk.revert_rate_12mo:.1%}")
    col2.metric("Edit Velocity", risk.edit_velocity)
    col3.metric("Dominant Editor", risk.dominant_editor or "None")
    if risk.flip_flopped_sections:
        st.write("**Flip-flopped sections:**", ", ".join(risk.flip_flopped_sections))
    if risk.editor_imposed_norms:
        st.write("**Editor norms:**")
        for norm in risk.editor_imposed_norms:
            st.write(f"- {norm}")
    st.caption(risk.risk_narrative)


def render_grade_panel(grade: ContentGrade) -> None:
    st.subheader("Article Quality")
    st.metric("Grade", f"{grade.letter_grade} ({grade.overall_score:.1f}/10)")
    rows = [{"Dimension": dim, "Score": f"{score:.1f}"} for dim, score in grade.dimension_scores.items()]
    st.table(rows)
    st.caption(grade.narrative)


def render_plan_chart(
    article: WikiArticle, content_grade: ContentGrade,
    plan: ImprovementPlan, risk: EditorialRiskProfile,
) -> None:
    editing_names = {s.name for s in plan.sections_to_edit}
    excluded_names = set(plan.sections_excluded)
    flip_names = set(risk.flip_flopped_sections)
    rows = []
    for name in article.sections:
        score = content_grade.section_grades.get(name, 5.0)
        if name in excluded_names or name in flip_names:
            status = "excluded"
            label = "⛔ flip-flop" if name in flip_names else "⛔ excluded"
        elif name in editing_names:
            status = "editing"
            sp = next((s for s in plan.sections_to_edit if s.name == name), None)
            label = f"✏️ {' + '.join(MODE_SHORT.get(m, m) for m in sp.modes)}" if sp else "✏️ editing"
        else:
            status = "ok"
            label = "✓ no changes"
        rows.append({"name": name, "score": score, "status": status, "label": label})

    fig = go.Figure()
    for status, color in STATUS_COLORS.items():
        subset = [r for r in rows if r["status"] == status]
        if not subset:
            continue
        fig.add_trace(go.Bar(
            name=status.capitalize(),
            y=[r["name"] for r in subset],
            x=[r["score"] for r in subset],
            orientation="h",
            marker_color=color,
            text=[r["label"] for r in subset],
            textposition="inside",
            hovertemplate="%{y}: %{x:.1f}/10<br>%{text}<extra></extra>",
        ))
    fig.update_layout(
        barmode="overlay",
        xaxis=dict(title="Section quality (0–10)", range=[0, 10]),
        yaxis=dict(autorange="reversed"),
        height=max(300, len(rows) * 35),
        margin=dict(l=10, r=10, t=10, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(plan.narrative)


def render_section_diff(draft: dict) -> None:
    """Render one section's diff as a side-by-side HTML table."""
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
            st.html(_html_diff(orig, revised))
        cites_added = draft.get("citations_added", [])
        cites_removed = draft.get("citations_removed", [])
        if cites_added:
            st.write("**Citations added:**", ", ".join(cites_added))
        if cites_removed:
            st.write("**Citations removed:**", ", ".join(cites_removed))


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
    for dim, result in critique.dimension_results.items():
        icon = "✅" if result.verdict == "PASS" else "❌"
        st.write(f"{icon} **{dim.replace('_', ' ').title()}**: {result.notes}")
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
    st.divider()
    st.subheader("Submit to Wikipedia")
    st.text_area(
        "Edit summary (copy into Wikipedia's edit summary box)",
        proposal.disclosure_edit_summary,
        height=80,
    )
    col1, col2 = st.columns(2)
    if col1.button("✅ Approve edit", type="primary"):
        st.success("Approved. Copy the edit summary above and apply the diff to Wikipedia manually.")
    if col2.button("❌ Reject"):
        st.warning("Edit rejected.")


def render_claim_map(claim_map: ClaimMap) -> None:
    st.subheader("Claim Map")
    counts: dict[str, int] = {}
    for c in claim_map.claims:
        counts[c.status] = counts.get(c.status, 0) + 1
    cols = st.columns(4)
    for i, status in enumerate(["cited", "undercited", "uncited", "consensus-uncited"]):
        cols[i].metric(f"{CLAIM_ICONS[status]} {status.replace('-', ' ').title()}", counts.get(status, 0))
    with st.expander("Claims needing sources", expanded=True):
        needs_source = [c for c in claim_map.claims if c.status in ("uncited", "undercited")]
        if not needs_source:
            st.write("All claims are cited.")
        else:
            for claim in needs_source:
                st.write(f"{CLAIM_ICONS[claim.status]} {claim.text}")
    with st.expander("All claims"):
        for claim in claim_map.claims:
            icon = CLAIM_ICONS.get(claim.status, "?")
            cid = f" _(ref {claim.citation_id})_" if claim.citation_id else ""
            st.write(f"{icon} {claim.text}{cid}")


# ── Live streaming runner ──────────────────────────────────────────────────────

def run_and_render(url: str) -> None:
    """
    Stream events from the orchestrator. Each stage runs in a st.status() widget
    (thinking events appear as italic text; collapses on done). Result panels are
    rendered immediately below the progress area as soon as each stage's data arrives.
    """
    stage_widgets: dict[str, object] = {}
    accumulated: dict = {}  # all done-event data accumulated so far

    # Pre-create result containers so they appear below the progress section
    # in a predictable order as soon as data arrives.
    result_containers = {
        "intake":   st.container(),
        "plan":     st.container(),
        "claims":   st.container(),
        "sources":  st.container(),
        "drafts":   st.container(),
        "proposal": st.container(),
    }

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
                widget.update(
                    label=f"{icon} {done_label} — {event.message}",
                    state="complete", expanded=False,
                )
                if event.data:
                    accumulated.update(event.data)
                _render_inline(event, accumulated, result_containers)
            elif event.status == "error":
                widget.update(label=f"{icon} {event.message}", state="error", expanded=True)

    asyncio.run(stream())


def _render_inline(event, accumulated: dict, containers: dict) -> None:
    """Render a result panel immediately when the relevant stage completes."""

    if event.stage == "INTAKE" and "grade" in accumulated and "risk" in accumulated:
        with containers["intake"]:
            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                render_risk_panel(EditorialRiskProfile.model_validate(accumulated["risk"]))
            with col2:
                render_grade_panel(ContentGrade.model_validate(accumulated["grade"]))

    elif event.stage == "PLAN" and "plan" in accumulated and "article" in accumulated:
        with containers["plan"]:
            st.divider()
            st.subheader("Improvement Plan")
            render_plan_chart(
                WikiArticle.model_validate(accumulated["article"]),
                ContentGrade.model_validate(accumulated["grade"]),
                ImprovementPlan.model_validate(accumulated["plan"]),
                EditorialRiskProfile.model_validate(accumulated["risk"]),
            )

    elif event.stage == "CLAIMS" and "claim_map" in accumulated:
        with containers["claims"]:
            st.divider()
            render_claim_map(ClaimMap.model_validate(accumulated["claim_map"]))

    elif event.stage == "SOURCES" and "audit" in accumulated:
        with containers["sources"]:
            st.divider()
            st.subheader("Sources")
            tab1, tab2 = st.tabs(["Existing Citations", "New Sources"])
            with tab1:
                for s in accumulated["audit"]:
                    icon = "✅" if s["recommendation"] == "USE" else (
                        "⚠️" if s["recommendation"] == "WEAK" else "❌"
                    )
                    note = f" ({s['status']})" if s["status"] != "LIVE" else ""
                    st.write(
                        f"{icon} [{s['overall_score']:.1f}] `{s['domain_type']}`{note} — {s['url'][:80]}"
                    )
                    if s.get("claim_support_summary"):
                        st.caption(f"   {s['claim_support_summary']}")
            with tab2:
                for s in accumulated.get("new_sources", []):
                    st.write(f"➕ [{s['overall_score']:.1f}] `{s['domain_type']}` — {s['url'][:80]}")
                    if s.get("claim_support_summary"):
                        st.caption(f"   {s['claim_support_summary']}")

    elif event.stage == "DRAFT" and "section_drafts" in accumulated:
        with containers["drafts"]:
            st.divider()
            render_diff_view(accumulated["section_drafts"])

    elif event.stage == "GRADE" and "proposal" in accumulated:
        with containers["proposal"]:
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
