"""
cache.py — Best-effort Redis cache helpers for the graph endpoint.

Design principles:
  - All Redis operations are wrapped in try/except; a Redis failure is never
    allowed to break a real request (cache miss semantics on error).
  - The client is a module-level singleton — one connection pool per process.
  - TTL defaults to 60 s as a safety net even when invalidation misses an edge.
"""

import json

import redis.asyncio as aioredis

from app.core.config import settings

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return (or lazily create) the shared async Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URI, decode_responses=True
        )
    return _redis_client


# ─── Graph cache ──────────────────────────────────────────────────────────────

_GRAPH_KEY = "graph:{tenant_id}:{asset_id}"


async def get_cached_graph(tenant_id: str, asset_id: str) -> dict | None:
    """
    Return the cached graph dict, or None on a miss / Redis error.
    Callers should fall through to the repository on None.
    """
    client = await get_redis()
    try:
        data = await client.get(_GRAPH_KEY.format(tenant_id=tenant_id, asset_id=asset_id))
        return json.loads(data) if data else None
    except Exception:
        return None  # treat any Redis error as a cache miss


async def set_cached_graph(
    tenant_id: str, asset_id: str, graph: dict, ttl: int = 60
) -> None:
    """
    Persist *graph* in Redis under the tenant-scoped key.
    Failures are silently swallowed — caching is always best-effort.
    """
    client = await get_redis()
    try:
        await client.set(
            _GRAPH_KEY.format(tenant_id=tenant_id, asset_id=asset_id),
            json.dumps(graph),
            ex=ttl,
        )
    except Exception:
        pass  # never block a request on a cache write failure


async def invalidate_graph(tenant_id: str, asset_id: str) -> None:
    """
    Delete the cached graph for *asset_id* within *tenant_id*.
    Called from RelationshipService after a successful relationship write.
    Failures are silently swallowed.
    """
    client = await get_redis()
    try:
        await client.delete(_GRAPH_KEY.format(tenant_id=tenant_id, asset_id=asset_id))
    except Exception:
        pass
