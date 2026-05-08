# ABOUTME: Tests for orchestrator revision logic — no LLM calls.
# ABOUTME: Verifies critique feedback is injected into draft_section node params.

from models import TaskNode, CritiqueResult, SectionCritiqueResult, DimensionCritique
from orchestrator import _inject_revision_notes


def _failing_section(section_name: str, suggested_fix: str) -> SectionCritiqueResult:
    return SectionCritiqueResult(
        section_name=section_name,
        verdict="FAIL",
        dimensions={"improvement": DimensionCritique(verdict="FAIL", notes="truncated")},
        issues=["truncated"],
        suggested_fix=suggested_fix,
    )


def _draft_node(section: str, mode: str = "Expand") -> TaskNode:
    return TaskNode(id="t1", type="draft_section", params={"section": section, "mode": mode})


def test_inject_adds_fix_to_failing_draft_section():
    nodes = {"t1": _draft_node("Lead")}
    critique = CritiqueResult(
        overall_verdict="REVISE",
        failing_sections=["Lead"],
        section_results={"Lead": _failing_section("Lead", "Fix the truncated citation")},
    )
    _inject_revision_notes(nodes, critique)
    assert nodes["t1"].params["revision_notes"] == "Fix the truncated citation"


def test_inject_noop_when_critique_is_none():
    nodes = {"t1": _draft_node("Lead")}
    _inject_revision_notes(nodes, None)
    assert "revision_notes" not in nodes["t1"].params


def test_inject_skips_section_with_empty_fix():
    nodes = {"t1": _draft_node("Lead")}
    critique = CritiqueResult(
        overall_verdict="REVISE",
        section_results={"Lead": SectionCritiqueResult(
            section_name="Lead", verdict="FAIL", suggested_fix="",
        )},
    )
    _inject_revision_notes(nodes, critique)
    assert "revision_notes" not in nodes["t1"].params


def test_inject_ignores_non_draft_section_nodes():
    nodes = {"t1": TaskNode(id="t1", type="research_section", params={"section": "Lead"})}
    critique = CritiqueResult(
        overall_verdict="REVISE",
        section_results={"Lead": _failing_section("Lead", "Fix X")},
    )
    _inject_revision_notes(nodes, critique)
    assert "revision_notes" not in nodes["t1"].params


def test_inject_handles_multiple_nodes():
    nodes = {
        "t1": _draft_node("Lead"),
        "t2": _draft_node("History"),
    }
    critique = CritiqueResult(
        overall_verdict="REVISE",
        section_results={
            "Lead": _failing_section("Lead", "Expand the lead"),
            "History": _failing_section("History", "Fix citation at end"),
        },
    )
    _inject_revision_notes(nodes, critique)
    assert nodes["t1"].params["revision_notes"] == "Expand the lead"
    assert nodes["t2"].params["revision_notes"] == "Fix citation at end"


def test_inject_skips_section_not_in_critique():
    nodes = {"t1": _draft_node("Culture")}
    critique = CritiqueResult(
        overall_verdict="REVISE",
        section_results={"Lead": _failing_section("Lead", "Fix lead")},
    )
    _inject_revision_notes(nodes, critique)
    assert "revision_notes" not in nodes["t1"].params
