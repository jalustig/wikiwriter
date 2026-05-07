# ABOUTME: Tavily web search client for source discovery.
# ABOUTME: Returns structured search results suitable for LLM evaluation.

import asyncio
import os
from dotenv import load_dotenv

from cache import cached

load_dotenv()
_TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


@cached("search_results", ttl=48 * 3600)
async def search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web via Tavily. Returns list of {url, title, content} dicts."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=_TAVILY_API_KEY)
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.search(query, max_results=max_results),
    )
    results = response.get("results", [])
    return [
        {"url": r.get("url", ""), "title": r.get("title", ""), "content": r.get("content", "")}
        for r in results
    ]
