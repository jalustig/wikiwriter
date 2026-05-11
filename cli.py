# ABOUTME: Terminal interface for WikiWriter — run with --article <url>.
# ABOUTME: Streams the same orchestrator events as the Streamlit app, printed to stdout.

import argparse
import asyncio
import sys

from constants import STAGE_META
from dag import dag_layers
from tools.diff import section_diff
from models import ContentGrade, EditorialEnvironment, ArticleAssessment
from orchestrator import WikiWriterOrchestrator

CLAIM_ICONS = {"cited": "✅", "undercited": "⚠️", "uncited": "❌", "consensus-uncited": "ℹ️"}
_W = 72


def _sep(title: str = "") -> None:
    if title:
        print(f"\n── {title} {'─' * max(0, _W - len(title) - 4)}")
    else:
        print("\n" + "─" * _W)


def _print_environment(env: EditorialEnvironment) -> None:
    _sep("Editorial Environment")
    print(f"  Caution: {env.caution_level}")
    print(f"  Revert rate (12mo): {env.revert_rate_12mo:.1%}  |  Edit velocity: {env.edit_velocity}")
    if env.dominant_editor:
        print(f"  Dominant editor: {env.dominant_editor}")
    if env.flip_flopped_sections:
        print(f"  Flip-flopped: {', '.join(env.flip_flopped_sections)}")
    if env.editor_imposed_norms:
        for norm in env.editor_imposed_norms:
            print(f"  Norm: {norm}")
    if env.policies_and_restrictions:
        for policy in env.policies_and_restrictions:
            print(f"  Policy: {policy}")
    print(f"  {env.environment_narrative}")


def _print_grade(grade: ContentGrade) -> None:
    _sep("Article Quality")
    print(f"  Grade: {grade.letter_grade} ({grade.overall_score:.1f}/10)")
    for dim, score in grade.dimension_scores.items():
        bar = "█" * int(score) + "░" * (10 - int(score))
        print(f"  {dim:<28} {bar}  {score:.1f}")
    print(f"  {grade.narrative}")


def _print_assessment(assessment: ArticleAssessment) -> None:
    _sep("Article Assessment")
    print(f"  Importance: {assessment.importance.tier} — {assessment.importance.rationale}")
    print(f"  Class: {assessment.article_class} | Effort: {assessment.effort_ceiling}"
          f" | Scope: {assessment.edit_scope}")
    print(f"\n  Edit rationale: {assessment.edit_rationale}")
    if assessment.primary_weaknesses:
        print("\n  Primary weaknesses:")
        for w in assessment.primary_weaknesses:
            print(f"    • {w}")
    print("\n  Per-section decisions:")
    for s in assessment.sections:
        if s.action == "EDIT":
            print(f"    ✏️  {s.name:<40} [{s.edit_type}] — {s.rationale}")
        else:
            print(f"    ✓  {s.name:<40} SKIP — {s.rationale}")


def _print_dag(dag: dict, narrative: str) -> None:
    _sep("Task DAG")
    if not dag:
        print("  (empty)")
        return

    layers = dag_layers(dag)
    inner = _W - 4  # usable width inside the box borders

    for i, layer in enumerate(layers):
        # Build one display line per node in this layer
        lines = []
        for nid in layer:
            node = dag[nid]
            params_str = "  ".join(f"{k}={v}" for k, v in node.get("params", {}).items())
            label = f"[{nid}]  {node['type']}"
            if params_str:
                label += f"  {params_str}"
            deps = node.get("deps", [])
            if deps:
                label += f"  ← {', '.join(deps)}"
            lines.append(label)

        # Print layer box
        print(f"  ┌{'─' * inner}┐")
        for line in lines:
            print(f"  │  {line:<{inner - 2}}│")
        print(f"  └{'─' * inner}┘")

        # Arrow to next layer
        if i < len(layers) - 1:
            mid = inner // 2 + 2
            print(f"  {' ' * mid}│")
            print(f"  {' ' * mid}▼")

    print(f"\n  Plan: {narrative}")


def _print_sources(audit: list[dict], new_sources: list[dict]) -> None:
    _sep("Sources")
    print("  Existing citations:")
    for s in audit:
        icon = "✅" if s["recommendation"] == "USE" else (
            "⚠️" if s["recommendation"] == "WEAK" else "❌"
        )
        note = f" ({s['status']})" if s["status"] != "LIVE" else ""
        print(f"    {icon} [{s['overall_score']:.1f}] {s['domain_type']}{note} — {s['url'][:65]}")
        if s.get("topic_coverage_summary"):
            print(f"       {s['topic_coverage_summary']}")
    if new_sources:
        print("\n  New sources found:")
        for s in new_sources:
            print(f"    ➕ [{s['overall_score']:.1f}] {s['domain_type']} — {s['url'][:65]}")
            if s.get("topic_coverage_summary"):
                print(f"       {s['topic_coverage_summary']}")


def _print_diffs(section_drafts: list[dict]) -> None:
    _sep("Section Drafts")
    for draft in section_drafts:
        name = draft["section_name"]
        changes = draft.get("changes_made", [])
        print(f"\n  ── {name} {'─' * max(0, 50 - len(name))}")
        for c in changes:
            print(f"    • {c}")
        orig, revised = draft["original_text"], draft["revised_text"]
        if orig.strip() == revised.strip():
            print("    (no text changes)")
        else:
            for ln in section_diff(orig, revised, output="text", width=_W - 6, color=True):
                print(ln)
        for label, cites in (
            ("Citations added", draft.get("citations_added", [])),
            ("Citations removed", draft.get("citations_removed", [])),
        ):
            if cites:
                print(f"    {label}: {', '.join(cites)}")


def _print_critique(critique: dict) -> None:
    _sep("Critique")
    print(f"  Verdict: {critique['overall_verdict']}")
    if critique.get("passing_sections"):
        print(f"  Passing: {', '.join(critique['passing_sections'])}")
    if critique.get("failing_sections"):
        print(f"  Failing: {', '.join(critique['failing_sections'])}")
    for sec_name, sec_result in critique.get("section_results", {}).items():
        icon = "✓" if sec_result["verdict"] == "PASS" else "✗"
        print(f"  {icon} {sec_name}")
        for dim, data in sec_result.get("dimensions", {}).items():
            dim_icon = "✅" if data["verdict"] == "PASS" else "❌"
            print(f"       {dim_icon} {dim}: {data['notes']}")


def _print_proposal(proposal: dict) -> None:
    _sep("Edit Proposal")
    ig = proposal.get("input_grade", {})
    og = proposal.get("output_grade", {})
    print(f"  Input:  {ig.get('letter_grade', '?')} ({ig.get('overall_score', 0):.1f}/10)")
    print(f"  Output: {og.get('letter_grade', '?')} ({og.get('overall_score', 0):.1f}/10)")
    print(f"  Delta:  {proposal.get('quality_delta', 0):+.1f}")

    edit_summary = proposal.get("edit_summary", {})
    if edit_summary:
        _sep("Editorial Summary")
        print(f"  {edit_summary.get('narrative', '')}")
        print(f"\n  Edit summary line:\n    {edit_summary.get('disclosure_line', '')}")


# ── Terminal equivalent of app.py's _render_inline ────────────────────────────

def _render_results(event, accumulated: dict) -> None:
    if event.stage == "GATHER" and "grade" in accumulated and "environment" in accumulated:
        _print_environment(EditorialEnvironment.model_validate(accumulated["environment"]))
        _print_grade(ContentGrade.model_validate(accumulated["grade"]))
        if "audit" in accumulated:
            _print_sources(accumulated["audit"], accumulated.get("new_sources", []))

    elif event.stage == "ASSESS" and "assessment" in accumulated:
        _print_assessment(ArticleAssessment.model_validate(accumulated["assessment"]))

    elif event.stage == "PLAN" and "dag" in accumulated:
        _print_dag(accumulated["dag"], accumulated.get("dag_narrative", ""))

    elif event.stage == "EXEC" and "section_drafts" in accumulated:
        _print_diffs(accumulated["section_drafts"])

    elif event.stage == "CRITIQUE" and "critique" in accumulated:
        _print_critique(accumulated["critique"])

    elif event.stage == "GRADE" and "proposal" in accumulated:
        _print_proposal(accumulated["proposal"])


# ── Main stream loop ───────────────────────────────────────────────────────────

_STOP_AFTER_MAP = {
    "fetch": "FETCH",
    "gather": "GATHER",
    "assess": "ASSESS",
    "plan": "PLAN",
    "exec": "EXEC",
    "critique": "CRITIQUE",
    "grade": "GRADE",
}


async def _stream(url: str, stop_after: str | None = None) -> None:
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
            if "/" in event.message:
                print(f"   → {event.message}", flush=True)
        elif event.status == "done":
            print(f"✓  {done_label} — {event.message}", flush=True)
            if event.data:
                accumulated.update(event.data)
            _render_results(event, accumulated)
            if stop_after and stage == stop_after:
                return
        elif event.status == "error":
            print(f"✗  {event.message}", file=sys.stderr, flush=True)
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="WikiWriter — AI Wikipedia editor")
    parser.add_argument("--article", required=True, metavar="URL", help="Wikipedia article URL")
    parser.add_argument(
        "--stop-after", metavar="STAGE", choices=_STOP_AFTER_MAP,
        help=f"Stop after: {', '.join(_STOP_AFTER_MAP.keys())}",
    )
    args = parser.parse_args()
    stop_after = _STOP_AFTER_MAP.get(args.stop_after) if args.stop_after else None
    asyncio.run(_stream(args.article, stop_after=stop_after))


if __name__ == "__main__":
    main()
