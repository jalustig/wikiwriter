# ABOUTME: Tests for ArticleGrader prompt construction logic.
# ABOUTME: Verifies wikitext (including <ref> tags) is passed to the LLM for citation grading.

from models import WikiArticle
from workers.article_grader import _build_grader_prompt


def _make_article(wikitext: str = "", section_texts: dict | None = None) -> WikiArticle:
    return WikiArticle(
        title="Test Article",
        url="https://en.wikipedia.org/wiki/Test_Article",
        wikitext=wikitext,
        sections=list((section_texts or {}).keys()),
        section_texts=section_texts or {},
        citations=[],
        assessment_class=None,
    )


def test_prompt_includes_ref_tags_from_wikitext():
    wikitext = (
        "The sky is blue.<ref>{{cite book|title=Skies|author=A. Smith}}</ref>\n"
        "==History==\nSome history here.<ref name=\"foo\">Source</ref>\n"
    )
    article = _make_article(
        wikitext=wikitext,
        section_texts={"Lead": wikitext},
    )
    prompt = _build_grader_prompt(article)
    assert "<ref>" in prompt or '<ref name="foo">' in prompt


def test_prompt_includes_cite_templates():
    wikitext = "Claim.<ref>{{cite web|url=http://example.com|title=Example}}</ref>"
    article = _make_article(
        wikitext=wikitext,
        section_texts={"Lead": wikitext},
    )
    prompt = _build_grader_prompt(article)
    assert "cite web" in prompt


def test_prompt_includes_article_title():
    article = _make_article(
        wikitext="Some content",
        section_texts={"Lead": "Some content"},
    )
    article.title = "Service star"
    prompt = _build_grader_prompt(article)
    assert "Service star" in prompt


def test_all_sections_appear_in_prompt():
    """Every section in the article should appear in the grader prompt."""
    sections = ["Lead", "History", "Geography", "Economy", "Culture", "Demographics"]
    section_texts = {s: f"Content of {s} section." * 20 for s in sections}
    article = _make_article(
        wikitext="dummy",
        section_texts=section_texts,
    )
    article.sections = sections
    prompt = _build_grader_prompt(article)
    for name in sections:
        assert name in prompt, f"Section '{name}' missing from grader prompt"


def test_full_section_text_included():
    """Section text is not truncated — the LLM receives the full text."""
    long_text = "x" * 5000
    article = _make_article(
        wikitext="dummy",
        section_texts={"Lead": long_text},
    )
    prompt = _build_grader_prompt(article)
    assert "x" * 5000 in prompt
