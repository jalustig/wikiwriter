# ABOUTME: Streamlit app — live per-stage progress with inline thinking, then edit proposal review.
# ABOUTME: Each stage runs inside st.status(); collapses automatically when done.

import asyncio
import difflib

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

# (icon, running label, done label template)
STAGE_META = {
    "FETCH":    ("🌐", "Reading article…",           "Read article"),
    "INTAKE":   ("📊", "Assessing quality…",          "Quality assessed"),
    "PLAN":     ("🗺️",  "Planning edits…",             "Edit plan ready"),
    "CLAIMS":   ("🔎", "Tagging claims…",             "Claims tagged"),
    "SOURCES":  ("🔍", "Evaluating sources…",         "Sources evaluated"),
    "DRAFT":    ("✏️",  "Writing drafts…",             "Drafts written"),
    "CRITIQUE": ("🔬", "Reviewing draft…",            "Draft reviewed"),
    "GRADE":    ("📈", "Scoring output…",             "Output scored"),
}

RISK_COLORS = {"LOW": "green", "MODERATE": "orange", "HIGH": "red", "CRITICAL": "red"}
VERDICT_COLORS = {"PASS": "green", "REVISE": "orange", "DISCARD": "red"}
CLAIM_STATUS_ICONS = {
    "cited": "✅", "undercited": "⚠️", "uncited": "❌", "consensus-uncited": "ℹ️",
}


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
        st.write("**Editor-imposed norms:**")
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


def render_diff_view(section_drafts: list[dict]) -> None:
    st.subheader("Section Drafts")
    if not section_drafts:
        st.write("No drafts available.")
        return
    for draft in section_drafts:
        name = draft["section_name"]
        orig, revised = draft["original_text"], draft["revised_text"]
        changes = draft.get("changes_made", [])
        with st.expander(f"**{name}**" + (f" — {changes[0]}" if changes else ""), expanded=False):
            if changes:
                st.write("**Changes:**")
                for c in changes:
                    st.write(f"- {c}")
            diff = list(difflib.unified_diff(
                orig.splitlines(keepends=True), revised.splitlines(keepends=True),
                fromfile="original", tofile="revised", n=3,
            ))
            st.code("".join(diff) if diff else "(no changes)", language="diff")
            cites_added = draft.get("citations_added", [])
            cites_removed = draft.get("citations_removed", [])
            if cites_added:
                st.write("**Citations added:**", ", ".join(cites_added))
            if cites_removed:
                st.write("**Citations removed:**", ", ".join(cites_removed))


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
    col1.metric("Input Grade", proposal.input_grade.letter_grade,
                f"{proposal.input_grade.overall_score:.1f}/10")
    col2.metric("Output Grade", proposal.output_grade.letter_grade,
                f"{proposal.output_grade.overall_score:.1f}/10")
    col3.metric("Quality Delta", f"{proposal.quality_delta:+.1f}", delta_color="normal")
    render_critique_panel(proposal.critique)
    with st.expander("Article Diff", expanded=False):
        st.code(proposal.full_diff or "(no diff available)", language="diff")
    st.divider()
    st.subheader("Submit to Wikipedia")
    st.text_area(
        "Edit summary (copy this into Wikipedia's edit summary box)",
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
        icon = CLAIM_STATUS_ICONS[status]
        cols[i].metric(f"{icon} {status.replace('-', ' ').title()}", counts.get(status, 0))
    with st.expander("Claims needing sources", expanded=True):
        needs_source = [c for c in claim_map.claims if c.status in ("uncited", "undercited")]
        if not needs_source:
            st.write("All claims are cited.")
        else:
            for claim in needs_source:
                st.write(f"{CLAIM_STATUS_ICONS[claim.status]} {claim.text}")
    with st.expander("All claims"):
        for claim in claim_map.claims:
            icon = CLAIM_STATUS_ICONS.get(claim.status, "?")
            cid = f" _(ref {claim.citation_id})_" if claim.citation_id else ""
            st.write(f"{icon} {claim.text}{cid}")


# ── Live streaming runner ──────────────────────────────────────────────────────

def run_and_render(url: str) -> dict:
    """
    Stream events from the orchestrator, rendering each stage in a st.status() widget.
    Thinking events appear as italic text inside the status. Stages collapse when done.
    Returns a dict of accumulated event data for the results panels below.
    """
    stage_widgets: dict[str, object] = {}   # stage_key -> StatusContainer
    stage_done_labels: dict[str, str] = {}  # stage_key -> final label for collapse
    accumulated: dict = {}

    async def stream():
        async for event in WikiWriterOrchestrator().run(url):
            stage = event.stage
            icon, running_label, done_label = STAGE_META.get(stage, ("•", stage, stage))

            # Create the status widget on first event for this stage
            if stage not in stage_widgets:
                stage_widgets[stage] = st.status(f"{icon} {running_label}", expanded=True)

            widget = stage_widgets[stage]

            if event.status == "thinking":
                widget.markdown(f"*{event.message}*")
            elif event.status == "running":
                # For progress counters (contains "/"), update the widget label
                if "/" in event.message:
                    widget.update(label=f"{icon} {event.message}")
                else:
                    widget.markdown(event.message)
            elif event.status == "done":
                label = f"{icon} {done_label} — {event.message}"
                stage_done_labels[stage] = label
                widget.update(label=label, state="complete", expanded=False)
                if event.data:
                    accumulated.update(event.data)
            elif event.status == "error":
                widget.update(
                    label=f"{icon} {event.message}",
                    state="error",
                    expanded=True,
                )

    asyncio.run(stream())
    return accumulated


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

    accumulated = run_and_render(url)

    if not accumulated:
        st.error("Agent did not produce results — check that the URL is a valid Wikipedia article.")
        return

    # Build structured results from accumulated event data
    if "grade" not in accumulated or "risk" not in accumulated or "plan" not in accumulated:
        st.error("Agent did not complete planning.")
        return

    risk = EditorialRiskProfile.model_validate(accumulated["risk"])
    grade = ContentGrade.model_validate(accumulated["grade"])
    plan = ImprovementPlan.model_validate(accumulated["plan"])
    article = WikiArticle.model_validate(accumulated["article"])

    st.divider()
    render_risk_panel(risk)

    st.divider()
    render_grade_panel(grade)

    st.divider()
    st.subheader("Improvement Plan")
    render_plan_chart(article, grade, plan, risk)

    if "claim_map" in accumulated:
        st.divider()
        render_claim_map(ClaimMap.model_validate(accumulated["claim_map"]))

    if "section_drafts" in accumulated:
        st.divider()
        render_diff_view(accumulated["section_drafts"])

    if "audit" in accumulated and "new_sources" in accumulated:
        st.divider()
        st.subheader("Sources")
        tab1, tab2 = st.tabs(["Existing Citations", "New Sources"])
        with tab1:
            for s in accumulated["audit"]:
                icon = "✅" if s["recommendation"] == "USE" else "⚠️" if s["recommendation"] == "WEAK" else "❌"
                status_note = f" ({s['status']})" if s["status"] != "LIVE" else ""
                st.write(
                    f"{icon} [{s['overall_score']:.1f}] `{s['domain_type']}`{status_note}"
                    f" — {s['url'][:80]}"
                )
                if s.get("claim_support_summary"):
                    st.caption(f"   {s['claim_support_summary']}")
        with tab2:
            for s in accumulated["new_sources"]:
                st.write(f"➕ [{s['overall_score']:.1f}] `{s['domain_type']}` — {s['url'][:80]}")
                if s.get("claim_support_summary"):
                    st.caption(f"   {s['claim_support_summary']}")

    if "proposal" in accumulated:
        st.divider()
        render_proposal_panel(EditProposal.model_validate(accumulated["proposal"]))
    elif "critique" in accumulated:
        st.divider()
        render_critique_panel(CritiqueResult.model_validate(accumulated["critique"]))


if __name__ == "__main__":
    main()
