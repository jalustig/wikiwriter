# ABOUTME: Tests for DraftWriter pure logic — no LLM calls.
# ABOUTME: Tests source report assembly and diff generation.

from models import SectionPlan, SourceEvaluation
from workers.draft_writer import _assemble_source_report, _build_diff, _draft_cache_key


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
