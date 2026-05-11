# ABOUTME: Produces a brief topic+scope summary of a Wikipedia article for use by other workers.
# ABOUTME: Used by evaluate_source and research_section to assess source relevance.

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from cache import cache, cache_key, record_llm_start, record_llm_tokens
from utils.log import log_llm_call, log_llm_response
from models import WikiArticle, ArticleSummary

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_PROMPT = (Path(__file__).parent.parent / "prompts" / "summarize_article.txt").read_text()
_MODEL = os.getenv("FAST_MODEL", "gpt-5.4")


def _article_text(article: WikiArticle) -> str:
    parts = []
    for name in article.sections[:8]:  # first 8 sections is enough
        text = article.section_texts.get(name, "")
        if text.strip():
            parts.append(f"== {name} ==\n{text}" if name != "Lead" else text)
    return "\n\n".join(parts)[:6000]


async def summarize_article(article: WikiArticle) -> ArticleSummary:
    key = cache_key("summarize_article", article.url)
    if key in cache:
        return ArticleSummary.model_validate(cache[key])

    prompt = _PROMPT.format(
        article_title=article.title,
        article_text=_article_text(article),
    )

    log_llm_call("summarize_article", _MODEL, prompt)
    record_llm_start()
    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    record_llm_tokens(response.usage)
    raw_text = response.choices[0].message.content
    log_llm_response("summarize_article", raw_text,
                     getattr(response.usage, "prompt_tokens", 0),
                     getattr(response.usage, "completion_tokens", 0))
    data = json.loads(raw_text)
    result = ArticleSummary(
        topic=data.get("topic", f"{article.title} — topic not extracted"),
        scope=data.get("scope", "Scope not determined"),
    )
    cache.set(key, result.model_dump(), expire=3600)
    return result
