# ABOUTME: Streamlit app — live pipeline progress and edit proposal review UI.
# ABOUTME: Grows incrementally across milestones; each milestone adds new panels.

import asyncio
import difflib

import plotly.graph_objects as go
import streamlit as st

from models import ProgressEvent, WikiArticle, ContentGrade, EditorialRiskProfile, ImprovementPlan, ClaimMap
from orchestrator import WikiWriterOrchestrator

STATUS_COLORS = {
    "editing":  "#2196F3",   # blue
    "excluded": "#F44336",   # red
    "ok":       "#4CAF50",   # green
}

MODE_SHORT = {
    "Citation Repair":     "Cite Fix",
    "Claim Attribution":   "Cite Add",
    "Section Expansion":   "Expand",
    "Section Rewrite":     "Rewrite",
    "Contradiction Integration": "Contradict",
    "Synthesis Pass":      "Synthesis",
}

STAGE_LABELS = {
    "FETCH": "Fetch article",
    "INTAKE": "Grade & analyze",
    "PLAN": "Plan edits",
    "CLAIMS": "Extract claims",
    "SOURCES": "Audit & discover sources",
    "DRAFT": "Draft sections",
}

RISK_COLORS = {
    "LOW": "green",
    "MODERATE": "orange",
    "HIGH": "red",
    "CRITICAL": "red",
}


def run_pipeline_sync(url: str) -> list[ProgressEvent]:
    """Run the async pipeline and collect events synchronously for Streamlit."""
    events: list[ProgressEvent] = []

    async def collect():
        async for event in WikiWriterOrchestrator().run(url):
            events.append(event)

    asyncio.run(collect())
    return events


def render_progress(events: list[ProgressEvent]) -> None:
    st.subheader("Pipeline Progress")
    seen_stages: dict[str, ProgressEvent] = {}
    for event in events:
        seen_stages[event.stage] = event

    for stage_key, label in STAGE_LABELS.items():
        event = seen_stages.get(stage_key)
        if event is None:
            st.write(f"⬜ {label}")
        elif event.status == "running":
            st.write(f"🔄 {label}: {event.message}")
        elif event.status == "done":
            st.write(f"✅ {label}: {event.message}")
        elif event.status == "error":
            st.write(f"❌ {label}: {event.message}")


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

    rows = [
        {"Dimension": dim, "Score": f"{score:.1f}"}
        for dim, score in grade.dimension_scores.items()
    ]
    st.table(rows)
    st.caption(grade.narrative)


def render_plan_chart(
    article: WikiArticle,
    content_grade: ContentGrade,
    plan: ImprovementPlan,
    risk: EditorialRiskProfile,
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
            section_plan = next((s for s in plan.sections_to_edit if s.name == name), None)
            if section_plan:
                short_modes = " + ".join(MODE_SHORT.get(m, m) for m in section_plan.modes)
                label = f"✏️ {short_modes}"
            else:
                label = "✏️ editing"
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
        orig = draft["original_text"]
        revised = draft["revised_text"]
        changes = draft.get("changes_made", [])

        with st.expander(f"**{name}**" + (f" — {changes[0]}" if changes else ""), expanded=False):
            if changes:
                st.write("**Changes:**")
                for c in changes:
                    st.write(f"- {c}")

            orig_lines = orig.splitlines(keepends=True)
            rev_lines = revised.splitlines(keepends=True)
            diff = list(difflib.unified_diff(
                orig_lines, rev_lines, fromfile="original", tofile="revised", n=3
            ))
            if diff:
                st.code("".join(diff), language="diff")
            else:
                st.write("_(no changes)_")

            cites_added = draft.get("citations_added", [])
            cites_removed = draft.get("citations_removed", [])
            if cites_added:
                st.write("**Citations added:**", ", ".join(cites_added))
            if cites_removed:
                st.write("**Citations removed:**", ", ".join(cites_removed))


CLAIM_STATUS_ICONS = {
    "cited": "✅",
    "undercited": "⚠️",
    "uncited": "❌",
    "consensus-uncited": "ℹ️",
}


def render_claim_map(claim_map: ClaimMap) -> None:
    st.subheader("Claim Map")
    counts = {}
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
                icon = CLAIM_STATUS_ICONS[claim.status]
                st.write(f"{icon} {claim.text}")

    with st.expander("All claims"):
        for claim in claim_map.claims:
            icon = CLAIM_STATUS_ICONS.get(claim.status, "?")
            cid = f" _(ref {claim.citation_id})_" if claim.citation_id else ""
            st.write(f"{icon} {claim.text}{cid}")


def main():
    st.set_page_config(page_title="WikiWriter", layout="wide")
    st.title("WikiWriter")

    url = st.text_input(
        "Wikipedia article URL",
        placeholder="https://en.wikipedia.org/wiki/Service_star",
    )
    analyse = st.button("Analyse")

    if not analyse or not url:
        return

    with st.spinner("Running pipeline…"):
        events = run_pipeline_sync(url)

    render_progress(events)

    # Extract final data from PLAN done event
    plan_event = next(
        (e for e in reversed(events) if e.stage == "PLAN" and e.status == "done"),
        None,
    )
    intake_event = next(
        (e for e in reversed(events) if e.stage == "INTAKE" and e.status == "done"),
        None,
    )

    if not intake_event or not plan_event:
        st.error("Pipeline did not complete successfully.")
        return

    risk = EditorialRiskProfile.model_validate(intake_event.data["risk"])
    grade = ContentGrade.model_validate(intake_event.data["grade"])
    plan = ImprovementPlan.model_validate(plan_event.data["plan"])
    article = WikiArticle.model_validate(plan_event.data["article"])

    # Accumulate final_data from all SOURCES done events
    final_data: dict = {}
    for event in events:
        if event.stage == "SOURCES" and event.status == "done" and event.data:
            final_data.update(event.data)

    st.divider()
    render_risk_panel(risk)

    st.divider()
    render_grade_panel(grade)

    st.divider()
    st.subheader("Improvement Plan")
    render_plan_chart(article, grade, plan, risk)

    # Extract claim map if available
    claims_event = next(
        (e for e in reversed(events) if e.stage == "CLAIMS" and e.status == "done"),
        None,
    )
    if claims_event and claims_event.data:
        st.divider()
        claim_map = ClaimMap.model_validate(claims_event.data["claim_map"])
        render_claim_map(claim_map)

    # Render draft diff view
    draft_event = next(
        (e for e in reversed(events) if e.stage == "DRAFT" and e.status == "done"),
        None,
    )
    if draft_event and draft_event.data:
        st.divider()
        render_diff_view(draft_event.data.get("section_drafts", []))

    if "audit" in final_data and "new_sources" in final_data:
        st.divider()
        st.subheader("Sources")
        tab1, tab2 = st.tabs(["Existing Citations", "New Sources"])
        with tab1:
            for s in final_data["audit"]:
                icon = "✅" if s["recommendation"] == "USE" else "⚠️" if s["recommendation"] == "WEAK" else "❌"
                status_note = f" ({s['status']})" if s["status"] != "LIVE" else ""
                st.write(
                    f"{icon} [{s['overall_score']:.1f}] `{s['domain_type']}`{status_note}"
                    f" — {s['url'][:80]}"
                )
                if s.get("claim_support_summary"):
                    st.caption(f"   {s['claim_support_summary']}")
        with tab2:
            for s in final_data["new_sources"]:
                st.write(f"➕ [{s['overall_score']:.1f}] `{s['domain_type']}` — {s['url'][:80]}")
                if s.get("claim_support_summary"):
                    st.caption(f"   {s['claim_support_summary']}")


if __name__ == "__main__":
    main()
