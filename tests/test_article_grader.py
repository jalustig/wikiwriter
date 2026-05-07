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
    article = _make_article(wikitext=wikitext)
    prompt = _build_grader_prompt("Test Article", wikitext)
    assert "<ref>" in prompt or '<ref name="foo">' in prompt


def test_prompt_includes_cite_templates():
    wikitext = "Claim.<ref>{{cite web|url=http://example.com|title=Example}}</ref>"
    prompt = _build_grader_prompt("Test Article", wikitext)
    assert "cite web" in prompt


def test_prompt_includes_article_title():
    prompt = _build_grader_prompt("Service star", "Some content")
    assert "Service star" in prompt
