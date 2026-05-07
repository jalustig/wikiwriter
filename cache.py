# ABOUTME: Persistent disk cache for all expensive external operations.
# ABOUTME: SHA-256 cache key. Use @cached on standalone async functions only — not instance methods.

import diskcache
import hashlib
import json
import os
from functools import wraps
from dotenv import load_dotenv

load_dotenv()
CACHE_DIR = os.getenv("CACHE_DIR", ".wikiwriter_cache")
cache = diskcache.Cache(CACHE_DIR)

_stats: dict[str, int] = {"hits": 0, "misses": 0}


def get_cache_stats() -> dict[str, int]:
    return dict(_stats)


def reset_cache_stats() -> None:
    _stats["hits"] = _stats["misses"] = 0


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
