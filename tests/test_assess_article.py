# ABOUTME: Tests for assess_article worker — section cap enforcement and no-edit logic.
# ABOUTME: Tests the deterministic post-LLM processing, not the LLM call itself.

from models import (
    ArticleImportance, SectionDecision, WikiArticle,
)
from workers.assess_article import (
    _enforce_section_cap, _build_assessment, _build_section_scores, _build_article_text,
)


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


# ── _build_section_scores: endmatter filtering ─────────────────────────────

def test_section_scores_excludes_references():
    scores = _build_section_scores(["History", "References"], {"History": 6.0, "References": 8.0})
    assert "History" in scores
    assert "References" not in scores


def test_section_scores_excludes_all_endmatter_variants():
    endmatter = ["References", "Citations", "Sources", "Notes",
                 "Bibliography", "Further reading", "External links", "See also"]
    scores = _build_section_scores(endmatter, {})
    assert scores == ""


def test_section_scores_case_insensitive():
    scores = _build_section_scores(["REFERENCES", "History"], {})
    assert "REFERENCES" not in scores
    assert "History" in scores


def test_section_scores_preserves_content_sections():
    sections = ["Lead", "History", "Reception", "References"]
    grades = {"Lead": 7.0, "History": 5.5, "Reception": 8.0, "References": 9.0}
    scores = _build_section_scores(sections, grades)
    assert "Lead: 7.0" in scores
    assert "History: 5.5" in scores
    assert "Reception: 8.0" in scores
    assert "References" not in scores


def test_section_scores_defaults_missing_grade_to_5():
    scores = _build_section_scores(["History"], {})
    assert "History: 5.0" in scores


# ── _build_article_text ─────────────────────────────────────────────────────

def _make_wiki_article(sections, section_texts):
    return WikiArticle(
        title="Test",
        url="https://en.wikipedia.org/wiki/Test",
        wikitext="",
        sections=sections,
        section_texts=section_texts,
        citations=[],
        assessment_class=None,
    )


def test_build_article_text_includes_all_sections():
    sections = ["Lead", "History", "Geography"]
    texts = {s: f"Text of {s}." for s in sections}
    article = _make_wiki_article(sections, texts)
    result = _build_article_text(article)
    assert "Lead" in result
    assert "History" in result
    assert "Geography" in result


def test_build_article_text_no_truncation():
    """Section text is never truncated — LLM receives full content."""
    long_text = "x" * 5000
    article = _make_wiki_article(["Lead"], {"Lead": long_text})
    result = _build_article_text(article)
    assert "x" * 5000 in result


def test_build_article_text_all_sections_included():
    """All sections appear in output, not just the first few."""
    sections = [f"S{i}" for i in range(30)]
    texts = {s: f"Content of {s}." for s in sections}
    article = _make_wiki_article(sections, texts)
    result = _build_article_text(article)
    for name in sections:
        assert name in result


# ── focused pass: cap behaviour ─────────────────────────────────────────────

def test_cap_not_applied_on_non_final_pass():
    """Pass 1 for COMPLETE article: cap should NOT be enforced."""
    raw = _raw_normal()
    raw["article_class"] = "COMPLETE"
    raw["sections"] = [
        {"name": f"S{i}", "action": "EDIT", "edit_type": "EXPAND", "rationale": "thin"}
        for i in range(5)
    ]
    result = _build_assessment(raw, flip_flopped=set(), is_final=False)
    edits = [s for s in result.sections if s.action == "EDIT"]
    assert len(edits) == 5  # cap not enforced on non-final pass


def test_cap_applied_when_is_final():
    """Final pass always enforces the cap."""
    raw = _raw_normal()
    raw["article_class"] = "COMPLETE"
    raw["sections"] = [
        {"name": f"S{i}", "action": "EDIT", "edit_type": "EXPAND", "rationale": "thin"}
        for i in range(5)
    ]
    result = _build_assessment(raw, flip_flopped=set(), is_final=True)
    edits = [s for s in result.sections if s.action == "EDIT"]
    assert len(edits) <= 3
