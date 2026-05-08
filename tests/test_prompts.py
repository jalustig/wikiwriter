# ABOUTME: Sanity checks that prompt files contain required rules.
# ABOUTME: Catches missing guardrails without requiring LLM calls.

from pathlib import Path

_PROMPTS = Path(__file__).parent.parent / "prompts"


def test_draft_writer_prompt_forbids_editorial_notes():
    text = (_PROMPTS / "draft_writer.txt").read_text().lower()
    assert "do not include editorial notes" in text
