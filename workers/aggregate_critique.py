# ABOUTME: Aggregates per-section critique results into an overall editorial verdict.
# ABOUTME: Produces PASS/REVISE/PARTIAL_ACCEPT/DISCARD with section-level instructions.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache, cache_key
from models import SectionCritiqueResult, CritiqueResult, DimensionCritique

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "aggregate_critique.txt").read_text()
_MODEL = os.getenv("CRITIC_MODEL", "gpt-4o")


def _format_section_results(section_results: list[SectionCritiqueResult]) -> str:
    lines = []
    for r in section_results:
        lines.append(f"### {r.section_name}: {r.verdict}")
        for dim, data in r.dimensions.items():
            lines.append(f"  {dim}: {data.verdict} — {data.notes}")
        if r.issues:
            for issue in r.issues:
                lines.append(f"  Issue: {issue}")
        if r.suggested_fix:
            lines.append(f"  Fix needed: {r.suggested_fix}")
    return "\n".join(lines)


async def aggregate_critique(
    article_title: str,
    section_results: list[SectionCritiqueResult],
    cycle: int = 0,
) -> CritiqueResult:
    key = cache_key(
        "aggregate_critique",
        article_title,
        [r.model_dump_json() for r in section_results],
        cycle,
    )
    if key in cache:
        return CritiqueResult.model_validate(cache[key])

    # Fast path: if all sections pass, no LLM needed
    if all(r.verdict == "PASS" for r in section_results):
        result = CritiqueResult(
            overall_verdict="PASS",
            passing_sections=[r.section_name for r in section_results],
            failing_sections=[],
            section_results={r.section_name: r for r in section_results},
        )
        cache.set(key, result.model_dump(), expire=3600)
        return result

    prompt = _PROMPT.format(
        article_title=article_title,
        cycle=cycle + 1,
        section_results=_format_section_results(section_results),
    )

    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    raw = json.loads(response.choices[0].message.content)

    # Build revision instructions from section-level suggested_fix fields
    failing = raw.get("failing_sections", [])
    revision_instructions = []
    section_map = {r.section_name: r for r in section_results}
    for sec_name in failing:
        if sec_name in section_map and section_map[sec_name].suggested_fix:
            revision_instructions.append(
                f"{sec_name}: {section_map[sec_name].suggested_fix}"
            )

    # Also include LLM-provided instructions
    for instr in raw.get("revision_instructions", []):
        if instr not in revision_instructions:
            revision_instructions.append(instr)

    result = CritiqueResult(
        overall_verdict=raw.get("overall_verdict", "REVISE"),
        revision_scope=raw.get("revision_scope"),
        passing_sections=raw.get("passing_sections", []),
        failing_sections=failing,
        revision_instructions=revision_instructions,
        discard_reason=raw.get("discard_reason") if raw.get("discard_reason") != "null" else None,
        section_results={r.section_name: r for r in section_results},
    )
    cache.set(key, result.model_dump(), expire=3600)
    return result
