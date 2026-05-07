# ABOUTME: Terminal interface for WikiWriter — run with --article <url>.
# ABOUTME: Streams the same orchestrator events as the Streamlit app, printed to stdout.

import argparse
import asyncio
import difflib
import re
import sys

from constants import STAGE_META
from models import (
    WikiArticle, ContentGrade, EditorialRiskProfile,
    ImprovementPlan, ClaimMap, EditProposal,
)
from orchestrator import WikiWriterOrchestrator

CLAIM_ICONS = {"cited": "✅", "undercited": "⚠️", "uncited": "❌", "consensus-uncited": "ℹ️"}
_W = 72


def _sep(title: str = "") -> None:
    if title:
        print(f"\n── {title} {'─' * max(0, _W - len(title) - 4)}")
    else:
        print("\n" + "─" * _W)


def _print_risk(risk: EditorialRiskProfile) -> None:
    _sep("Editorial Risk")
    print(f"  Tier: {risk.risk_tier}")
    print(f"  Revert rate (12mo): {risk.revert_rate_12mo:.1%}  |  Edit velocity: {risk.edit_velocity}")
    if risk.dominant_editor:
        print(f"  Dominant editor: {risk.dominant_editor}")
    if risk.flip_flopped_sections:
        print(f"  Flip-flopped: {', '.join(risk.flip_flopped_sections)}")
    if risk.editor_imposed_norms:
        for norm in risk.editor_imposed_norms:
            print(f"  Norm: {norm}")
    print(f"  {risk.risk_narrative}")


def _print_grade(grade: ContentGrade) -> None:
    _sep("Article Quality")
    print(f"  Grade: {grade.letter_grade} ({grade.overall_score:.1f}/10)")
    for dim, score in grade.dimension_scores.items():
        bar = "█" * int(score) + "░" * (10 - int(score))
        print(f"  {dim:<28} {bar}  {score:.1f}")
    print(f"  {grade.narrative}")


def _print_plan(
    article: WikiArticle,
    grade: ContentGrade,
    plan: ImprovementPlan,
    risk: EditorialRiskProfile,
) -> None:
    _sep("Improvement Plan")
    editing = {s.name: s for s in plan.sections_to_edit}
    excluded = set(plan.sections_excluded)
    flip = set(risk.flip_flopped_sections)
    for name in article.sections:
        score = grade.section_grades.get(name, 5.0)
        if name in flip:
            print(f"  ⛔ {name:<40} {score:.1f}  (flip-flop)")
        elif name in excluded:
            print(f"  ⛔ {name:<40} {score:.1f}  (excluded)")
        elif name in editing:
            modes = ", ".join(editing[name].modes)
            print(f"  ✏️  {name:<39} {score:.1f}  [{modes}]")
        else:
            print(f"  ✓  {name:<40} {score:.1f}")
    print(f"\n  {plan.narrative}")


def _print_claims(claim_map: ClaimMap) -> None:
    _sep("Claim Map")
    counts: dict[str, int] = {}
    for c in claim_map.claims:
        counts[c.status] = counts.get(c.status, 0) + 1
    for status, icon in CLAIM_ICONS.items():
        print(f"  {icon}  {status.replace('-', ' ').title()}: {counts.get(status, 0)}")
    needs = [c for c in claim_map.claims if c.status in ("uncited", "undercited")]
    if needs:
        print("\n  Claims needing sources:")
        for c in needs:
            print(f"    {CLAIM_ICONS[c.status]}  {c.text}")


def _print_sources(audit: list[dict], new_sources: list[dict]) -> None:
    _sep("Sources")
    print("  Existing citations:")
    for s in audit:
        icon = "✅" if s["recommendation"] == "USE" else (
            "⚠️" if s["recommendation"] == "WEAK" else "❌"
        )
        note = f" ({s['status']})" if s["status"] != "LIVE" else ""
        print(f"    {icon} [{s['overall_score']:.1f}] {s['domain_type']}{note} — {s['url'][:65]}")
        if s.get("claim_support_summary"):
            print(f"       {s['claim_support_summary']}")
    if new_sources:
        print("\n  New sources found:")
        for s in new_sources:
            print(f"    ➕ [{s['overall_score']:.1f}] {s['domain_type']} — {s['url'][:65]}")
            if s.get("claim_support_summary"):
                print(f"       {s['claim_support_summary']}")


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def _print_diffs(section_drafts: list[dict]) -> None:
    _sep("Section Drafts")
    for draft in section_drafts:
        name = draft["section_name"]
        changes = draft.get("changes_made", [])
        print(f"\n  ── {name} {'─' * max(0, 50 - len(name))}")
        for c in changes:
            print(f"    • {c}")
        orig, revised = draft["original_text"], draft["revised_text"]
        if orig.strip() != revised.strip():
            diff = difflib.unified_diff(
                _split_sentences(orig),
                _split_sentences(revised),
                fromfile="original", tofile="revised",
                lineterm="",
            )
            for line in list(diff)[2:]:  # skip --- / +++ header
                marker = line[0] if line else " "
                print(f"    {marker} {line[1:]}")
        for label, cites in (
            ("Citations added", draft.get("citations_added", [])),
            ("Citations removed", draft.get("citations_removed", [])),
        ):
            if cites:
                print(f"    {label}: {', '.join(cites)}")


def _print_proposal(proposal: EditProposal) -> None:
    _sep("Edit Proposal")
    ig, og = proposal.input_grade, proposal.output_grade
    print(f"  Input:  {ig.letter_grade} ({ig.overall_score:.1f}/10)")
    print(f"  Output: {og.letter_grade} ({og.overall_score:.1f}/10)")
    print(f"  Delta:  {proposal.quality_delta:+.1f}")
    print(f"\n  Critique: {proposal.critique.overall_verdict}")
    for dim, result in proposal.critique.dimension_results.items():
        icon = "✅" if result.verdict == "PASS" else "❌"
        print(f"    {icon}  {dim.replace('_', ' ').title()}: {result.notes}")
    if proposal.critique.discard_reason:
        print(f"\n  Discard reason: {proposal.critique.discard_reason}")
    print(f"\n  Edit summary:\n    {proposal.disclosure_edit_summary}")


# ── Terminal equivalent of app.py's _render_inline ────────────────────────────

def _render_results(event, accumulated: dict) -> None:
    if event.stage == "INTAKE" and "grade" in accumulated and "risk" in accumulated:
        _print_risk(EditorialRiskProfile.model_validate(accumulated["risk"]))
        _print_grade(ContentGrade.model_validate(accumulated["grade"]))

    elif event.stage == "PLAN" and "plan" in accumulated and "article" in accumulated:
        _print_plan(
            WikiArticle.model_validate(accumulated["article"]),
            ContentGrade.model_validate(accumulated["grade"]),
            ImprovementPlan.model_validate(accumulated["plan"]),
            EditorialRiskProfile.model_validate(accumulated["risk"]),
        )

    elif event.stage == "CLAIMS" and "claim_map" in accumulated:
        _print_claims(ClaimMap.model_validate(accumulated["claim_map"]))

    elif event.stage == "SOURCES" and "audit" in accumulated:
        _print_sources(accumulated["audit"], accumulated.get("new_sources", []))

    elif event.stage == "DRAFT" and "section_drafts" in accumulated:
        _print_diffs(accumulated["section_drafts"])

    elif event.stage == "GRADE" and "proposal" in accumulated:
        _print_proposal(EditProposal.model_validate(accumulated["proposal"]))


# ── Main stream loop ───────────────────────────────────────────────────────────

async def _stream(url: str) -> None:
    accumulated: dict = {}
    current_stage: str | None = None

    async for event in WikiWriterOrchestrator().run(url):
        stage = event.stage
        icon, running_label, done_label = STAGE_META.get(stage, ("•", stage, stage))

        if stage != current_stage:
            current_stage = stage
            print(f"\n{icon}  {running_label}", flush=True)

        if event.status == "thinking":
            print(f"   ✦ {event.message}", flush=True)
        elif event.status == "running":
            # Only print counter-style updates (e.g. "3/20 sources"); skip generic labels
            if "/" in event.message:
                print(f"   → {event.message}", flush=True)
        elif event.status == "done":
            print(f"✓  {done_label} — {event.message}", flush=True)
            if event.data:
                accumulated.update(event.data)
            _render_results(event, accumulated)
        elif event.status == "error":
            print(f"✗  {event.message}", file=sys.stderr, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="WikiWriter — AI Wikipedia editor")
    parser.add_argument("--article", required=True, metavar="URL", help="Wikipedia article URL")
    args = parser.parse_args()
    asyncio.run(_stream(args.article))


if __name__ == "__main__":
    main()
