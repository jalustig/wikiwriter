# ABOUTME: Tests for critique_section prompt building — no LLM calls.
# ABOUTME: Verifies full section text is passed to critic without truncation.

from workers.critique_section import _build_critique_prompt


def test_critique_prompt_includes_full_revised_text_beyond_3000_chars():
    long_text = "encyclopedic sentence about Texas. " * 200  # ~7000 chars
    prompt = _build_critique_prompt(
        article_title="Texas",
        section_name="Lead",
        original_text="short original",
        revised_text=long_text,
        source_report="some sources",
    )
    assert long_text.strip() in prompt


def test_critique_prompt_includes_full_source_report_beyond_2000_chars():
    long_report = "https://example.com/source covers topic X. " * 100  # ~4300 chars
    prompt = _build_critique_prompt(
        article_title="Texas",
        section_name="Lead",
        original_text="original",
        revised_text="revised",
        source_report=long_report,
    )
    assert long_report.strip() in prompt


def test_critique_prompt_uses_fallback_when_source_report_empty():
    prompt = _build_critique_prompt(
        article_title="Texas",
        section_name="Lead",
        original_text="original",
        revised_text="revised",
        source_report="",
    )
    assert "No sources available" in prompt
