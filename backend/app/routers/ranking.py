"""GET /ranking (REQUIREMENTS §4.3).

The ranking result is wrapped in an in-process TTL cache (see
``ttl_cache.py``): page-1 is hammered every 30s by every connected client,
so memoising for a few seconds lets PostgreSQL skip the window-function work
on cache hits. Any successful write to /transaction clears the cache so the
board stays fresh after activity.
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.config import get_settings
from app.database import get_conn
from app.middleware.ttl_cache import TTLCache
from app.models import RankingResponse
from app.services.ranking_service import get_ranking

router = APIRouter()

# Module-level cache initialised lazily (also referenced by the transaction
# service for invalidation).
_cache: TTLCache[tuple[int, int], dict] | None = None


def _get_cache() -> TTLCache[tuple[int, int], dict]:
    global _cache
    if _cache is None:
        _cache = TTLCache(ttl_seconds=get_settings().ranking_cache_ttl)
    return _cache


@router.get("/ranking", response_model=RankingResponse)
async def get_leaderboard(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # Update the shared cache reference so the transaction service can clear it.
    import app.services.transaction_service as ts
    ts.ranking_cache = _get_cache()

    async def compute() -> dict:
        result = await get_ranking(conn, page, limit)
        return result.model_dump(mode="json")

    data = await _get_cache().get_or_compute((page, limit), compute)
    return data
