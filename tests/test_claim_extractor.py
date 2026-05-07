# ABOUTME: Tests for ClaimExtractor — pure logic only, no LLM calls.
# ABOUTME: Tests section filtering, claim deduplication, and output structure.

from models import WikiArticle, ImprovementPlan, SectionPlan, Claim
from workers.claim_extractor import ClaimExtractor, _sections_to_analyze, _deduplicate_claims


def _make_article(sections=None, section_texts=None) -> WikiArticle:
    if sections is None:
        sections = ["Lead", "History", "Reception", "See also"]
    if section_texts is None:
        section_texts = {s: f"Text for {s}." for s in sections}
    return WikiArticle(
        title="Test Article",
        url="https://en.wikipedia.org/wiki/Test_Article",
        wikitext="",
        sections=sections,
        section_texts=section_texts,
        citations=[],
        assessment_class=None,
    )


def _make_plan(edit_names=None, excluded=None) -> ImprovementPlan:
    edit_names = edit_names or []
    excluded = excluded or []
    return ImprovementPlan(
        sections_to_edit=[
            SectionPlan(name=n, modes=["Section Expansion"], rationale="needs work")
            for n in edit_names
        ],
        sections_excluded=excluded,
        exclusion_reasons={e: "stable" for e in excluded},
        narrative="Plan narrative",
    )


# --- _sections_to_analyze ---

def test_sections_to_analyze_returns_planned_only():
    article = _make_article()
    plan = _make_plan(edit_names=["History", "Reception"])
    result = _sections_to_analyze(article, plan)
    assert result == ["History", "Reception"]


def test_sections_to_analyze_preserves_article_order():
    article = _make_article(sections=["Lead", "A", "B", "C"])
    plan = _make_plan(edit_names=["C", "A"])
    result = _sections_to_analyze(article, plan)
    # Should follow article section order, not plan order
    assert result == ["A", "C"]


def test_sections_to_analyze_skips_missing_section_text():
    article = _make_article(
        sections=["Lead", "History"],
        section_texts={"Lead": "Lead text."},  # History has no text
    )
    plan = _make_plan(edit_names=["History"])
    result = _sections_to_analyze(article, plan)
    assert result == []


def test_sections_to_analyze_empty_plan():
    article = _make_article()
    plan = _make_plan(edit_names=[])
    result = _sections_to_analyze(article, plan)
    assert result == []


def test_sections_to_analyze_skips_empty_text():
    article = _make_article(
        sections=["Lead", "History"],
        section_texts={"Lead": "Lead text.", "History": "   "},
    )
    plan = _make_plan(edit_names=["Lead", "History"])
    result = _sections_to_analyze(article, plan)
    assert result == ["Lead"]


# --- _deduplicate_claims ---

def test_deduplicate_removes_exact_duplicates():
    claims = [
        Claim(text="The sky is blue.", status="uncited"),
        Claim(text="The sky is blue.", status="uncited"),
        Claim(text="Water is wet.", status="cited", citation_id="0"),
    ]
    result = _deduplicate_claims(claims)
    assert len(result) == 2
    texts = [c.text for c in result]
    assert "The sky is blue." in texts
    assert "Water is wet." in texts


def test_deduplicate_keeps_all_unique():
    claims = [
        Claim(text="A.", status="uncited"),
        Claim(text="B.", status="cited", citation_id="1"),
        Claim(text="C.", status="consensus-uncited"),
    ]
    result = _deduplicate_claims(claims)
    assert len(result) == 3


def test_deduplicate_preserves_order():
    claims = [
        Claim(text="First.", status="uncited"),
        Claim(text="Second.", status="undercited"),
        Claim(text="Third.", status="cited", citation_id="2"),
    ]
    result = _deduplicate_claims(claims)
    assert [c.text for c in result] == ["First.", "Second.", "Third."]


def test_deduplicate_empty():
    assert _deduplicate_claims([]) == []


# --- ClaimExtractor structural tests ---

def test_extractor_initializes():
    extractor = ClaimExtractor()
    assert extractor is not None
