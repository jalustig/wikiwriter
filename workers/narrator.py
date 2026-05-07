# ABOUTME: Generates natural first-person thought-process commentary using an LLM.
# ABOUTME: Called at key decision points in the orchestrator; fails silently on error.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "narrator.txt").read_text()
_MODEL = os.getenv("NARRATOR_MODEL", os.getenv("DRAFT_MODEL", "gpt-5.4"))


async def narrate(stage: str, context: dict) -> str:
    """Return 2-3 sentences of first-person thinking about the current stage.

    Returns an empty string on any error so callers never need to handle exceptions.
    """
    try:
        context_text = json.dumps(context, indent=2, default=str)
        prompt = _PROMPT.replace("{stage}", stage).replace("{context}", context_text)
        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=150,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        import sys
        print(f"[narrator] {stage}: {e}", file=sys.stderr)
        return ""
