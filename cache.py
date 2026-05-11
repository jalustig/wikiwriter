# ABOUTME: Persistent disk cache for all expensive external operations.
# ABOUTME: SHA-256 cache key. Use @cached on standalone async functions only — not instance methods.

import diskcache
import hashlib
import json
import os
import shutil
import sqlite3
from functools import wraps
from dotenv import load_dotenv

load_dotenv()
_project_root = os.path.dirname(__file__)
_cache_dir_raw = os.getenv("CACHE_DIR", ".wikiwriter_cache")
CACHE_DIR = os.path.join(_project_root, _cache_dir_raw) if not os.path.isabs(_cache_dir_raw) else _cache_dir_raw


def _open_cache(directory: str) -> diskcache.Cache:
    try:
        c = diskcache.Cache(directory)
        # Verify the DB schema is intact by issuing a trivial query.
        c.stats()
        return c
    except (sqlite3.DatabaseError, diskcache.Timeout):
        shutil.rmtree(directory, ignore_errors=True)
        return diskcache.Cache(directory)


cache = _open_cache(CACHE_DIR)

_stats: dict[str, int] = {"hits": 0, "misses": 0}
_telemetry: dict = {
    "llm_calls": 0,
    "tokens_in": 0,
    "tokens_out": 0,
    "tool_calls": {},   # tool_name -> count
}


def get_cache_stats() -> dict[str, int]:
    return dict(_stats)


def reset_cache_stats() -> None:
    _stats["hits"] = _stats["misses"] = 0


def record_llm_start() -> None:
    """Increment LLM call counter at submission time, before awaiting the response."""
    _telemetry["llm_calls"] += 1


def record_llm_tokens(usage) -> None:
    """Record token counts after the LLM response arrives."""
    if usage is not None:
        _telemetry["tokens_in"] += getattr(usage, "prompt_tokens", 0) or 0
        _telemetry["tokens_out"] += getattr(usage, "completion_tokens", 0) or 0


def record_tool_call(tool: str) -> None:
    _telemetry["tool_calls"][tool] = _telemetry["tool_calls"].get(tool, 0) + 1


def get_telemetry() -> dict:
    return {
        "llm_calls": _telemetry["llm_calls"],
        "tokens_in": _telemetry["tokens_in"],
        "tokens_out": _telemetry["tokens_out"],
        "tool_calls": dict(_telemetry["tool_calls"]),
    }


def reset_telemetry() -> None:
    _telemetry["llm_calls"] = 0
    _telemetry["tokens_in"] = 0
    _telemetry["tokens_out"] = 0
    _telemetry["tool_calls"] = {}


def cache_key(*args, **kwargs) -> str:
    """Deterministic cache key from any JSON-serialisable inputs."""
    payload = json.dumps((args, kwargs), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def cached(namespace: str, ttl: int | None = None):
    """
    Decorator for standalone async functions only.
    Do NOT apply to instance methods — self pollutes the cache key.
    For workers, call cache_key() and check/set cache manually.
    """
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            key = f"{namespace}:{cache_key(*args, **kwargs)}"
            if key in cache:
                _stats["hits"] += 1
                return cache[key]
            _stats["misses"] += 1
            result = await fn(*args, **kwargs)
            if ttl is not None:
                cache.set(key, result, expire=ttl)
            else:
                cache[key] = result
            return result
        return wrapper
    return decorator
