# ABOUTME: Generates a brief factual summary of outcomes at the end of each pipeline stage.
# ABOUTME: Distinct from the stream-of-consciousness narrator — states decisions, not thinking.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import record_llm_start, record_llm_tokens
from utils.log import log_llm_call, log_llm_response

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "stage_summary.txt").read_text()
_MODEL = os.getenv("NARRATOR_MODEL", os.getenv("DRAFT_MODEL", "gpt-5.4"))


async def summarize_stage(stage: str, context: dict) -> str:
    """Return a 2-3 sentence factual summary of what was decided/found at this stage."""
    context_text = json.dumps(context, indent=2, default=str)
    prompt = _PROMPT.replace("{stage}", stage).replace("{context}", context_text)
    try:
        log_llm_call("stage_summarizer", _MODEL, prompt)
        record_llm_start()
        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=750,
            temperature=0.4,
        )
        record_llm_tokens(response.usage)
        raw_text = response.choices[0].message.content
        log_llm_response("stage_summarizer", raw_text,
                         getattr(response.usage, "prompt_tokens", 0),
                         getattr(response.usage, "completion_tokens", 0))
        return raw_text.strip()
    except Exception as e:
        import sys
        print(f"[stage_summarizer] {stage}: {e}", file=sys.stderr)
        return ""
