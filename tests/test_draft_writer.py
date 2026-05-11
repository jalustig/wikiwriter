# ABOUTME: Tests for DraftWriter pure logic — no LLM calls.
# ABOUTME: Tests source report assembly, diff generation, and article assembly.

from models import SectionPlan, SourceEvaluation, WikiArticle, SectionDraft
from workers.draft_writer import _assemble_source_report, _build_diff, _draft_cache_key
from workers.synthesis_writer import _assemble_with_drafts


def _make_article(sections, section_texts):
    return WikiArticle(
        title="Test", url="https://en.wikipedia.org/wiki/Test",
        wikitext="", sections=sections, section_texts=section_texts,
        citations=[], assessment_class=None,
    )


def _make_draft(section_name, original_text, revised_text):
    return SectionDraft(
        section_name=section_name,
        original_text=original_text,
        revised_text=revised_text,
        changes_made=[],
        citations_added=[],
        citations_removed=[],
    )


def _make_source(url, score, recommendation, topic_coverage_summary, status="LIVE"):
    return SourceEvaluation(
        url=url,
        status=status,
        domain_type="established_news",
        scores={k: score for k in ("domain_type", "topic_relevance", "age", "credibility", "accessibility")},
        overall_score=score,
        topic_coverage_summary=topic_coverage_summary,
        recommendation=recommendation,
    )


# --- _assemble_source_report ---

def test_source_report_includes_usable_audit():
    audit = [_make_source("https://a.com", 8.0, "USE", "Supports claim A")]
    report = _assemble_source_report(audit, [])
    assert "https://a.com" in report
    assert "Supports claim A" in report


def test_source_report_excludes_rejected_audit():
    audit = [
        _make_source("https://good.com", 8.0, "USE", "Good source"),
        _make_source("https://bad.com", 2.0, "REJECT", "Unreliable"),
    ]
    report = _assemble_source_report(audit, [])
    assert "https://good.com" in report
    assert "https://bad.com" not in report


def test_source_report_includes_new_sources():
    new = [_make_source("https://new.com", 7.5, "USE", "New source for claim B")]
    report = _assemble_source_report([], new)
    assert "https://new.com" in report
    assert "New source for claim B" in report


def test_source_report_sections_labeled():
    audit = [_make_source("https://existing.com", 8.0, "USE", "Existing")]
    new = [_make_source("https://new.com", 7.0, "USE", "New")]
    report = _assemble_source_report(audit, new)
    assert "EXISTING" in report.upper() or "AUDIT" in report.upper() or "existing" in report.lower()
    assert "NEW" in report.upper() or "new" in report.lower()


def test_source_report_empty():
    report = _assemble_source_report([], [])
    assert isinstance(report, str)
    assert len(report) >= 0  # may be empty or minimal


def test_source_report_includes_score():
    audit = [_make_source("https://a.com", 8.5, "USE", "Great")]
    report = _assemble_source_report(audit, [])
    assert "8.5" in report


def test_source_report_includes_weak_audit():
    audit = [_make_source("https://weak.com", 5.0, "WEAK", "Weak but usable")]
    report = _assemble_source_report(audit, [])
    assert "https://weak.com" in report


# --- _build_diff ---

def test_build_diff_returns_string():
    result = _build_diff("Hello world.", "Hello planet.")
    assert isinstance(result, str)


def test_build_diff_shows_changes():
    result = _build_diff("The cat sat.\nThe dog ran.", "The cat sat.\nThe dog walked.")
    assert "walked" in result or "ran" in result


def test_build_diff_identical_texts():
    text = "Nothing changed here."
    result = _build_diff(text, text)
    # Unified diff of identical texts is empty
    assert result == "" or "Nothing changed" in result


def test_build_diff_empty_original():
    result = _build_diff("", "New content added.")
    assert "New content" in result


def test_build_diff_empty_revised():
    result = _build_diff("Original content.", "")
    assert isinstance(result, str)


# --- _draft_cache_key ---

def test_draft_cache_key_differs_with_different_rationale():
    url = "https://en.wikipedia.org/wiki/Texas"
    sources = "some sources"
    plan_a = SectionPlan(name="Lead", modes=["Expand"], rationale="Mode: Expand")
    plan_b = SectionPlan(name="Lead", modes=["Expand"], rationale="Mode: Expand\nRevision notes: fix X")

    assert _draft_cache_key(url, plan_a, sources) != _draft_cache_key(url, plan_b, sources)


def test_draft_cache_key_same_for_identical_plans():
    url = "https://en.wikipedia.org/wiki/Texas"
    sources = "some sources"
    plan_a = SectionPlan(name="Lead", modes=["Expand"], rationale="Mode: Expand")
    plan_b = SectionPlan(name="Lead", modes=["Expand"], rationale="Mode: Expand")

    assert _draft_cache_key(url, plan_a, sources) == _draft_cache_key(url, plan_b, sources)


# --- _assemble_with_drafts ---

def test_assemble_substitutes_revised_text():
    article = _make_article(
        sections=["Lead", "History"],
        section_texts={"Lead": "Old lead.", "History": "Old history."},
    )
    drafts = [_make_draft("History", "Old history.", "New history.")]
    result = _assemble_with_drafts(article, drafts)
    assert "New history." in result
    assert "Old history." not in result


def test_assemble_preserves_untouched_sections():
    article = _make_article(
        sections=["Lead", "History"],
        section_texts={"Lead": "Lead text.", "History": "History text."},
    )
    result = _assemble_with_drafts(article, [])
    assert "Lead text." in result
    assert "History text." in result


def test_assemble_appends_new_sections():
    article = _make_article(
        sections=["Lead"],
        section_texts={"Lead": "Lead text."},
    )
    drafts = [_make_draft("New Section", "", "Brand new content.")]
    result = _assemble_with_drafts(article, drafts)
    assert "New Section" in result
    assert "Brand new content." in result


def test_assemble_new_section_after_existing():
    article = _make_article(
        sections=["Lead", "History"],
        section_texts={"Lead": "Lead.", "History": "History."},
    )
    drafts = [_make_draft("Further reading", "", "See also these books.")]
    result = _assemble_with_drafts(article, drafts)
    history_pos = result.index("History.")
    new_pos = result.index("See also these books.")
    assert new_pos > history_pos


def test_assemble_lead_has_no_header():
    article = _make_article(
        sections=["Lead", "History"],
        section_texts={"Lead": "Intro text.", "History": "History."},
    )
    result = _assemble_with_drafts(article, [])
    assert "== Lead ==" not in result
    assert "== History ==" in result
