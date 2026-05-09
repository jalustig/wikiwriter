# ABOUTME: Generates a brief factual summary of outcomes at the end of each pipeline stage.
# ABOUTME: Distinct from the stream-of-consciousness narrator — states decisions, not thinking.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import record_llm_call

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "stage_summary.txt").read_text()
_MODEL = os.getenv("NARRATOR_MODEL", os.getenv("DRAFT_MODEL", "gpt-5.4"))


async def summarize_stage(stage: str, context: dict) -> str:
    """Return a 2-3 sentence factual summary of what was decided/found at this stage."""
    context_text = json.dumps(context, indent=2, default=str)
    prompt = _PROMPT.replace("{stage}", stage).replace("{context}", context_text)
    try:
        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=150,
            temperature=0.4,
        )
        record_llm_call(response.usage)
        return response.choices[0].message.content.strip()
    except Exception as e:
        import sys
        print(f"[stage_summarizer] {stage}: {e}", file=sys.stderr)
        return ""
