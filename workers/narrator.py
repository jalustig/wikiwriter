# ABOUTME: Generates natural first-person thought-process commentary using an LLM.
# ABOUTME: Called at key decision points in the orchestrator; fails silently on error.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "narrator.txt").read_text()
_MODEL = os.getenv("NARRATOR_MODEL", os.getenv("DRAFT_MODEL", "gpt-5.4"))


async def narrate(stage: str, context: dict) -> list[str]:
    """Return a list of short stream-of-consciousness thoughts for this stage.

    Each element is one thought (1-2 sentences). Returns [] on any error.
    """
    try:
        context_text = json.dumps(context, indent=2, default=str)
        prompt = _PROMPT.replace("{stage}", stage).replace("{context}", context_text)
        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=300,
            temperature=0.85,
        )
        raw = response.choices[0].message.content.strip()
        thoughts = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        return thoughts
    except Exception as e:
        import sys
        print(f"[narrator] {stage}: {e}", file=sys.stderr)
        return []
