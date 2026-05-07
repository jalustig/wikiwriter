# ABOUTME: Persistent disk cache for all expensive external operations.
# ABOUTME: Cache key is a deterministic SHA-256 hash of inputs. Use @cached only on standalone async functions.

from __future__ import annotations
import diskcache
import hashlib
import json
import os
from functools import wraps
from dotenv import load_dotenv

load_dotenv()
CACHE_DIR = os.getenv("CACHE_DIR", ".wikiwriter_cache")
cache = diskcache.Cache(CACHE_DIR)


def cache_key(*args) -> str:
    """Deterministic cache key from any JSON-serialisable inputs."""
    payload = json.dumps(args, sort_keys=True, default=str)
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
                return cache[key]
            result = await fn(*args, **kwargs)
            if ttl is not None:
                cache.set(key, result, expire=ttl)
            else:
                cache[key] = result
            return result
        return wrapper
    return decorator
