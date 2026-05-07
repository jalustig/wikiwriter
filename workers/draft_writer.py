# ABOUTME: Section editor — rewrites Wikipedia article sections with improved citations and prose.
# ABOUTME: Exposes run() for initial drafts and revise() for critic-driven revision.

import difflib
import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache_key, cache
from models import WikiArticle, SectionPlan, SectionDraft, SourceEvaluation

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "draft_writer.txt").read_text()
_MODEL = os.getenv("DRAFT_MODEL", "gpt-5.4")


def _assemble_source_report(
    audit_results: list[SourceEvaluation],
    new_sources: list[SourceEvaluation],
) -> str:
    """Build a human-readable source report for the draft writer prompt."""
    lines: list[str] = []

    usable_audit = [s for s in audit_results if s.recommendation in ("USE", "WEAK")]
    if usable_audit:
        lines.append("EXISTING CITATIONS (usable):")
        for s in usable_audit:
            tag = "WEAK" if s.recommendation == "WEAK" else "USE"
            lines.append(f"  [{tag} {s.overall_score:.1f}] {s.url}")
            lines.append(f"    {s.topic_coverage_summary}")
        lines.append("")

    if new_sources:
        lines.append("NEW SOURCES FOUND:")
        for s in new_sources:
            lines.append(f"  [{s.overall_score:.1f}] {s.url}")
            lines.append(f"    {s.topic_coverage_summary}")
        lines.append("")

    return "\n".join(lines)


def _build_diff(original: str, revised: str) -> str:
    """Return unified diff between original and revised text."""
    orig_lines = original.splitlines(keepends=True)
    rev_lines = revised.splitlines(keepends=True)
    diff = list(difflib.unified_diff(orig_lines, rev_lines, fromfile="original", tofile="revised"))
    return "".join(diff)


class DraftWriter:
    async def run(
        self,
        section_plan: SectionPlan,
        article: WikiArticle,
        source_report: str,
        editor_norms: list[str],
    ) -> SectionDraft:
        section_text = article.section_texts.get(section_plan.name, "")

        cache_ns = f"draft_writer:{cache_key(article.url, section_plan.name, source_report, section_plan.modes)}"  # noqa: E501
        if cache_ns in cache:
            return SectionDraft.model_validate(cache[cache_ns])

        norms_text = "\n".join(f"- {n}" for n in editor_norms) if editor_norms else "None documented."
        modes_text = ", ".join(section_plan.modes)
        task_block = (
            f"Edit modes to apply: {modes_text}\n"
            f"Rationale: {section_plan.rationale}\n\n"
            f"Apply the specified edit modes to improve this section.\n\n"
            f"Return JSON with this structure:\n"
            f'{{"revised_text": "...", "changes_made": [...], '
            f'"citations_added": [...], "citations_removed": [...]}}'
        )

        prompt = _PROMPT.format(
            mode="DRAFT",
            article_title=article.title,
            section_name=section_plan.name,
            section_text=section_text,
            source_report=source_report or "No sources available.",
            editor_norms=norms_text,
            task_block=task_block,
        )

        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        raw = json.loads(response.choices[0].message.content)
        draft = SectionDraft(
            section_name=section_plan.name,
            original_text=section_text,
            revised_text=raw.get("revised_text", section_text),
            changes_made=raw.get("changes_made", []),
            citations_added=raw.get("citations_added", []),
            citations_removed=raw.get("citations_removed", []),
        )
        cache.set(cache_ns, draft.model_dump(), expire=3600)
        return draft

    async def revise(
        self,
        assembled_draft: str,
        revision_instructions: list[str],
        source_report: str,
    ) -> str:
        instructions_text = "\n".join(f"- {i}" for i in revision_instructions)
        task_block = (
            f"Revision instructions from critic:\n{instructions_text}\n\n"
            f"Fix only the listed issues. Do not change anything else.\n\n"
            f"Return the complete revised article text directly (no JSON wrapper)."
        )

        prompt = _PROMPT.format(
            mode="REVISE",
            article_title="(full article)",
            section_name="(full article)",
            section_text=assembled_draft,
            source_report=source_report or "No sources available.",
            editor_norms="None.",
            task_block=task_block,
        )

        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
