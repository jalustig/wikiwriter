# ABOUTME: Tavily web search client for source discovery.
# ABOUTME: Returns structured search results suitable for LLM evaluation.

import asyncio
import os
from dotenv import load_dotenv

from cache import cache, cache_key, record_tool_call
from utils.log import log_tool_call

load_dotenv()
_TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


async def search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web via Tavily. Returns list of {url, title, content} dicts."""
    from tavily import TavilyClient

    _key = f"search_results:{cache_key(query, max_results)}"
    record_tool_call("search")
    log_tool_call("search", {"query": query, "max_results": max_results})
    if _key in cache:
        return cache[_key]
    client = TavilyClient(api_key=_TAVILY_API_KEY)
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.search(query, max_results=max_results),
    )
    results = response.get("results", [])
    result = [
        {"url": r.get("url", ""), "title": r.get("title", ""), "content": r.get("content", "")}
        for r in results
    ]
    cache.set(_key, result, expire=48 * 3600)
    return result
