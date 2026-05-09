# ABOUTME: Generates natural first-person thought-process commentary using an LLM.
# ABOUTME: Streams thoughts line-by-line as an async generator; fails silently on error.

import os
from pathlib import Path
from typing import AsyncGenerator

from openai import AsyncOpenAI

from cache import record_llm_start, record_llm_tokens

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "narrator.txt").read_text()
_MODEL = os.getenv("NARRATOR_MODEL", os.getenv("DRAFT_MODEL", "gpt-5.4"))


async def narrate(stage: str, context_dict: dict) -> AsyncGenerator[str, None]:
    """Yield thoughts one line at a time as the LLM streams them."""
    import json
    context_text = json.dumps(context_dict, indent=2, default=str)
    prompt = _PROMPT.replace("{stage}", stage).replace("{context}", context_text)

    try:
        record_llm_start()
        stream = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=400,
            temperature=0.85,
            stream=True,
            stream_options={"include_usage": True},
        )

        buf = ""
        usage = None
        async for chunk in stream:
            if chunk.usage is not None:
                usage = chunk.usage
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta is None:
                continue
            buf += delta
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if line:
                    yield line

        # yield any remaining text after the stream ends
        remainder = buf.strip()
        if remainder:
            yield remainder

        record_llm_tokens(usage)

    except Exception as e:
        import sys
        print(f"[narrator] {stage}: {e}", file=sys.stderr)
