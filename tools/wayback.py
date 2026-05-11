# ABOUTME: Wayback Machine lookup for archived copies of dead URLs.
# ABOUTME: waybackpy is synchronous; runs via asyncio.run_in_executor.

from __future__ import annotations
import asyncio
from cache import cache_key, cache, record_tool_call
from utils.log import log_tool_call


async def get_archive_url(url: str) -> str | None:
    """Return newest Wayback Machine snapshot URL for a dead URL, or None."""
    key = f"wayback:{cache_key(url)}"
    record_tool_call("wayback")
    log_tool_call("wayback", {"url": url})
    if key in cache:
        return cache[key]
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _wayback_lookup_sync, url)
    cache.set(key, result, expire=7 * 24 * 3600)
    return result


def _wayback_lookup_sync(url: str) -> str | None:
    from waybackpy import WaybackMachineAvailabilityAPI
    try:
        api = WaybackMachineAvailabilityAPI(url, user_agent="WikiWriter/1.0")
        snapshot = api.newest()
        return snapshot.archive_url
    except Exception:
        return None
