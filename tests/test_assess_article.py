# ABOUTME: Tests for assess_article worker — section cap enforcement and no-edit logic.
# ABOUTME: Tests the deterministic post-LLM processing, not the LLM call itself.

import pytest
from models import (
    ArticleAssessment, ArticleImportance, SectionDecision,
)
from workers.assess_article import _enforce_section_cap, _build_assessment


def _importance(tier="MAJOR"):
    return ArticleImportance(
        tier=tier,
        rationale="Test article",
        expected_depth="solid",
    )


def _section(name, action="EDIT", edit_type="CITE_REPAIR"):
    return SectionDecision(name=name, action=action, edit_type=edit_type, rationale="needs work")


def _skip(name):
    return SectionDecision(name=name, action="SKIP", edit_type=None, rationale="fine")


# ── _enforce_section_cap ────────────────────────────────────────────────────

def test_section_cap_keeps_at_most_3_edit_sections():
    sections = [_section(f"S{i}") for i in range(6)]
    result = _enforce_section_cap(sections)
    edits = [s for s in result if s.action == "EDIT"]
    assert len(edits) <= 3


def test_section_cap_preserves_skip_sections():
    sections = [_section(f"S{i}") for i in range(5)] + [_skip("References")]
    result = _enforce_section_cap(sections)
    names = [s.name for s in result]
    assert "References" in names


def test_section_cap_demotes_excess_edits_to_skip():
    sections = [_section(f"S{i}") for i in range(5)]
    result = _enforce_section_cap(sections)
    skipped = [s for s in result if s.action == "SKIP"]
    # At least 2 were demoted
    assert len(skipped) >= 2


def test_section_cap_noop_when_3_or_fewer():
    sections = [_section("A"), _section("B"), _skip("C")]
    result = _enforce_section_cap(sections)
    edits = [s for s in result if s.action == "EDIT"]
    assert len(edits) == 2


def test_section_cap_noop_when_1_edit():
    sections = [_section("Only")]
    result = _enforce_section_cap(sections)
    assert result[0].action == "EDIT"


# ── _build_assessment: no-edit path ────────────────────────────────────────

def _raw_no_edit():
    return {
        "no_edit": True,
        "no_edit_reason": "BLP policy prohibits editing biography of living person without consensus.",
        "importance": {"tier": "MAJOR", "rationale": "Notable person", "expected_depth": "solid"},
        "article_class": "DEVELOPING",
        "effort_ceiling": "LIGHT",
        "edit_scope": "SPECIFIC_SECTIONS",
        "sections": [],
        "would_edit_sections": [
            {"name": "Early life", "action": "EDIT", "edit_type": "CITE_REPAIR",
             "rationale": "Several uncited claims"},
        ],
        "primary_weaknesses": ["Missing citations"],
        "source_quality_summary": "Mixed — several dead links.",
        "source_trust_verdict": "Treat with caution — several claims lack citations.",
        "edit_rationale": "Would improve citation coverage but BLP blocks editing.",
    }


def test_no_edit_flag_propagates():
    result = _build_assessment(_raw_no_edit(), flip_flopped=set())
    assert result.no_edit is True


def test_no_edit_reason_propagates():
    result = _build_assessment(_raw_no_edit(), flip_flopped=set())
    assert "BLP" in result.no_edit_reason


def test_no_edit_sections_empty():
    result = _build_assessment(_raw_no_edit(), flip_flopped=set())
    assert result.sections == []


def test_no_edit_would_edit_sections_populated():
    result = _build_assessment(_raw_no_edit(), flip_flopped=set())
    assert len(result.would_edit_sections) == 1
    assert result.would_edit_sections[0].name == "Early life"


def test_source_trust_verdict_propagates():
    result = _build_assessment(_raw_no_edit(), flip_flopped=set())
    assert "caution" in result.source_trust_verdict.lower()


# ── _build_assessment: normal edit path ────────────────────────────────────

def _raw_normal():
    return {
        "no_edit": False,
        "no_edit_reason": "",
        "importance": {"tier": "NOTABLE", "rationale": "Niche topic", "expected_depth": "brief"},
        "article_class": "STUB",
        "effort_ceiling": "MODERATE",
        "edit_scope": "SPECIFIC_SECTIONS",
        "sections": [
            {"name": f"S{i}", "action": "EDIT", "edit_type": "EXPAND", "rationale": "thin"}
            for i in range(5)
        ],
        "would_edit_sections": [],
        "primary_weaknesses": ["Thin content"],
        "source_quality_summary": "Decent.",
        "source_trust_verdict": "Reliable sources.",
        "edit_rationale": "Expand stub.",
    }


def test_normal_edit_sections_capped_at_3():
    result = _build_assessment(_raw_normal(), flip_flopped=set())
    assert len(result.sections) <= 3


def test_flip_flopped_section_forced_to_skip():
    raw = _raw_normal()
    raw["sections"] = [
        {"name": "History", "action": "EDIT", "edit_type": "EXPAND", "rationale": "thin"},
        {"name": "Lead", "action": "EDIT", "edit_type": "EXPAND", "rationale": "thin"},
    ]
    result = _build_assessment(raw, flip_flopped={"History"})
    history = next(s for s in result.sections if s.name == "History")
    assert history.action == "SKIP"


# ── scope_of_work ───────────────────────────────────────────────────────────

def test_scope_of_work_propagates():
    raw = _raw_normal()
    raw["scope_of_work"] = "We will expand the History and Lead sections to improve coverage."
    result = _build_assessment(raw, flip_flopped=set())
    assert result.scope_of_work == raw["scope_of_work"]


def test_scope_of_work_defaults_empty():
    result = _build_assessment(_raw_normal(), flip_flopped=set())
    assert result.scope_of_work == ""


def test_scope_of_work_propagates_no_edit_path():
    raw = _raw_no_edit()
    raw["scope_of_work"] = "No editing will be performed due to BLP restrictions."
    result = _build_assessment(raw, flip_flopped=set())
    assert result.scope_of_work == raw["scope_of_work"]
