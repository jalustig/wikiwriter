# ABOUTME: Translates editorial decisions (WHAT) into an executable task DAG (HOW).
# ABOUTME: Called after assess_article and after aggregate_critique on revision.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache, cache_key, record_llm_call
from models import ArticleAssessment, CritiqueResult, TaskNode
from dag import build_dag

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "edit_planner.txt").read_text()
_MODEL = os.getenv("DRAFT_MODEL", "gpt-4o")


def _assessment_json(assessment: ArticleAssessment) -> str:
    edit_sections = [s for s in assessment.sections if s.action == "EDIT"]
    return json.dumps({
        "edit_scope": assessment.edit_scope,
        "primary_weaknesses": assessment.primary_weaknesses,
        "edit_rationale": assessment.edit_rationale,
        "sections_to_edit": [
            {"name": s.name, "edit_type": s.edit_type, "rationale": s.rationale}
            for s in edit_sections
        ],
    }, indent=2)


def _revision_context(critique: CritiqueResult | None) -> str:
    if critique is None:
        return ""
    lines = ["## Revision Context (previous attempt failed critique)"]
    lines.append(f"Overall verdict: {critique.overall_verdict}")
    if critique.revision_scope:
        lines.append(f"Revision scope: {critique.revision_scope}")
    if critique.revision_instructions:
        lines.append("Instructions:")
        for instr in critique.revision_instructions:
            lines.append(f"  - {instr}")
    lines.append("Focus the plan on fixing the issues above.")
    return "\n".join(lines)


async def plan_edits(
    article_title: str,
    assessment: ArticleAssessment,
    critique: CritiqueResult | None = None,
) -> tuple[dict[str, TaskNode], str]:
    """
    Returns (nodes, narrative) where nodes is the executable task DAG.
    critique is provided on revision cycles.
    """
    cache_ns = cache_key(
        "edit_planner",
        article_title,
        assessment.model_dump_json(),
        critique.model_dump_json() if critique else "",
    )
    if cache_ns in cache:
        cached = cache[cache_ns]
        return build_dag(cached["tasks"]), cached["narrative"]

    prompt = _PROMPT.format(
        article_title=article_title,
        assessment_json=_assessment_json(assessment),
        effort_ceiling=assessment.effort_ceiling,
        revision_context=_revision_context(critique),
    )

    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    record_llm_call(response.usage)

    raw = json.loads(response.choices[0].message.content)
    tasks = raw.get("tasks", [])
    narrative = raw.get("narrative", "")

    cache.set(cache_ns, {"tasks": tasks, "narrative": narrative}, expire=3600)
    return build_dag(tasks), narrative


def format_dag_for_display(nodes: dict[str, TaskNode], narrative: str) -> str:
    """Format the DAG as human-readable text for CLI/log output."""
    lines = ["Task DAG:"]
    for node_id, node in nodes.items():
        deps = f" (after: {', '.join(node.deps)})" if node.deps else ""
        params_str = ", ".join(f"{k}={v}" for k, v in node.params.items())
        lines.append(f"  {node_id}: {node.type}({params_str}){deps}")
    lines.append(f"\nPlan: {narrative}")
    return "\n".join(lines)
