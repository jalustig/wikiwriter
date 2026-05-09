# ABOUTME: Evaluates assembled article draft across 7 quality dimensions.
# ABOUTME: Returns PASS/REVISE/DISCARD verdict with per-dimension notes and revision instructions.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache_key, cache, record_llm_start, record_llm_tokens
from models import DimensionCritique, CritiqueResult

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "critic.txt").read_text()
_MODEL = os.getenv("CRITIC_MODEL", "gpt-5.4")

# Dimensions where 3+ failures indicate irrecoverable quality problems
_CORE_DIMENSIONS = {"citation_coverage", "npov", "structural_completeness"}


def _derive_verdict(
    dimension_results: dict[str, DimensionCritique],
) -> tuple[str, str | None]:
    """Compute overall verdict from per-dimension results.

    PASS   — no failures, or exactly one non-core failure (minor issue, acceptable for incremental edits)
    REVISE — any core failure, or two or more failures of any kind
    DISCARD — all three core dimensions fail simultaneously
    """
    failed = [k for k, v in dimension_results.items() if v.verdict == "FAIL"]
    core_failures = [k for k in failed if k in _CORE_DIMENSIONS]

    if len(core_failures) == len(_CORE_DIMENSIONS):
        reason = f"All core dimensions failed: {', '.join(core_failures)}"
        return "DISCARD", reason
    if core_failures or len(failed) >= 2:
        return "REVISE", None
    return "PASS", None


class Critic:
    async def run(
        self,
        assembled_draft: str,
        source_report: str,
        sections_edited: list[str] | None = None,
    ) -> CritiqueResult:
        cache_ns = f"critic:{cache_key(assembled_draft, source_report, sections_edited)}"
        if cache_ns in cache:
            return CritiqueResult.model_validate(cache[cache_ns])

        edited_note = (
            f"Sections edited in this pass: {', '.join(sections_edited)}"
            if sections_edited else "All sections may have been touched."
        )
        prompt = _PROMPT.format(
            assembled_draft=assembled_draft,
            source_report=source_report or "No sources available.",
            sections_edited_note=edited_note,
        )

        record_llm_start()
        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        record_llm_tokens(response.usage)

        raw = json.loads(response.choices[0].message.content)

        dimension_results: dict[str, DimensionCritique] = {}
        for dim, result in raw.get("dimension_results", {}).items():
            try:
                dimension_results[dim] = DimensionCritique(
                    verdict=result["verdict"],
                    notes=result.get("notes", ""),
                )
            except (KeyError, ValueError):
                continue

        overall_verdict, discard_reason = _derive_verdict(dimension_results)

        revision_instructions = [
            f"{dim}: {dimension_results[dim].notes}"
            for dim in dimension_results
            if dimension_results[dim].verdict == "FAIL"
        ]

        result = CritiqueResult(
            overall_verdict=overall_verdict,
            dimension_results=dimension_results,
            revision_instructions=revision_instructions,
            discard_reason=discard_reason,
        )
        cache.set(cache_ns, result.model_dump(), expire=3600)
        return result
