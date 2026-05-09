# ABOUTME: Evaluates a single edited section against the original Wikipedia text.
# ABOUTME: Checks Wikipedia policy dimensions — WP:V, WP:NPOV, WP:NOR, WP:WEIGHT.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache, cache_key, record_llm_start, record_llm_tokens
from models import SectionCritiqueResult, DimensionCritique

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "critique_section.txt").read_text()
_MODEL = os.getenv("CRITIC_MODEL", "gpt-4o")


def _build_critique_prompt(
    article_title: str,
    section_name: str,
    original_text: str,
    revised_text: str,
    source_report: str,
) -> str:
    return _PROMPT.format(
        article_title=article_title,
        section_name=section_name,
        original_text=original_text,
        revised_text=revised_text,
        source_report=source_report or "No sources available.",
    )


async def critique_section(
    article_title: str,
    section_name: str,
    original_text: str,
    revised_text: str,
    source_report: str,
) -> SectionCritiqueResult:
    key = cache_key("critique_section", article_title, section_name, revised_text)
    if key in cache:
        return SectionCritiqueResult.model_validate(cache[key])

    # If no text change, auto-pass
    if original_text.strip() == revised_text.strip():
        result = SectionCritiqueResult(
            section_name=section_name,
            verdict="PASS",
            dimensions={
                d: DimensionCritique(verdict="PASS", notes="No changes made")
                for d in ("verifiability", "neutrality", "no_original_research",
                          "due_weight", "improvement")
            },
            issues=[],
            suggested_fix="",
        )
        cache.set(key, result.model_dump(), expire=3600)
        return result

    prompt = _build_critique_prompt(
        article_title, section_name, original_text, revised_text, source_report
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

    dimensions: dict[str, DimensionCritique] = {}
    for dim, data in raw.get("dimensions", {}).items():
        try:
            dimensions[dim] = DimensionCritique(
                verdict=data["verdict"],
                notes=data.get("notes", ""),
            )
        except (KeyError, ValueError):
            continue

    # Derive verdict: PASS if improvement=PASS and no policy dimension FAIL
    improvement = dimensions.get("improvement")
    policy_dims = {k: v for k, v in dimensions.items() if k != "improvement"}
    policy_failed = any(v.verdict == "FAIL" for v in policy_dims.values())

    if improvement and improvement.verdict == "PASS" and not policy_failed:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    result = SectionCritiqueResult(
        section_name=section_name,
        verdict=verdict,
        dimensions=dimensions,
        issues=raw.get("issues", []),
        suggested_fix=raw.get("suggested_fix", ""),
    )
    cache.set(key, result.model_dump(), expire=3600)
    return result
