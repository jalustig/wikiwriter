# ABOUTME: Lightweight LLM checkpoint that reviews a task plan before expensive execution.
# ABOUTME: Returns APPROVE or REVISE with specific feedback.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import record_llm_start, record_llm_tokens
from utils.log import log_llm_call, log_llm_response
from models import ArticleAssessment, TaskNode

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "plan_validate.txt").read_text()
_MODEL = os.getenv("FAST_MODEL", "gpt-5.4")


async def validate_plan(
    article_title: str,
    assessment: ArticleAssessment,
    nodes: dict[str, TaskNode],
) -> tuple[bool, str]:
    """
    Returns (approved, feedback).
    approved=True means proceed. approved=False means the plan needs revision.
    """
    edit_sections = [s for s in assessment.sections if s.action == "EDIT"]
    sections_to_edit = ", ".join(
        f"{s.name} ({s.edit_type})" for s in edit_sections
    )
    tasks_json = json.dumps(
        [{"id": n.id, "type": n.type, "params": n.params, "deps": n.deps}
         for n in nodes.values()],
        indent=2,
    )

    prompt = _PROMPT.format(
        article_title=article_title,
        sections_to_edit=sections_to_edit,
        effort_ceiling=assessment.effort_ceiling,
        edit_scope=assessment.edit_scope,
        tasks_json=tasks_json,
    )

    log_llm_call("plan_validate", _MODEL, prompt)
    record_llm_start()
    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    record_llm_tokens(response.usage)
    raw_text = response.choices[0].message.content
    log_llm_response("plan_validate", raw_text,
                     getattr(response.usage, "prompt_tokens", 0),
                     getattr(response.usage, "completion_tokens", 0))
    raw = json.loads(raw_text)
    approved = raw.get("verdict") == "APPROVE"
    feedback = raw.get("feedback", "")
    return approved, feedback
