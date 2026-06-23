"""asyncpg connection-pool lifecycle.

The pool is created lazily on app startup and closed on shutdown. Every
route handler acquires a connection via ``async with pool.acquire()`` so the
event loop is never blocked by a synchronous DB call (REQUIREMENTS §6.3).

We expose the pool as a module-level singleton plus a FastAPI dependency
``get_conn`` that hands out a managed connection and returns it to the pool
when the request ends.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

import asyncpg
from fastapi import Request

from app.config import get_settings

logger = logging.getLogger(__name__)

# Module-level singleton; populated by lifespan() on startup.
pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    """Create the global connection pool. Idempotent."""
    global pool
    if pool is not None:
        return
    settings = get_settings()
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_min_size,
        max_size=settings.db_max_size,
        command_timeout=settings.db_command_timeout,
        max_inactive_connection_lifetime=settings.db_max_inactive_connection_lifetime,
    )
    logger.info("asyncpg pool ready (min=%s max=%s)", settings.db_min_size, settings.db_max_size)


async def close_pool() -> None:
    """Close the pool on shutdown."""
    global pool
    if pool is not None:
        await pool.close()
        pool = None
        logger.info("asyncpg pool closed")


def get_db_pool(request: Request) -> asyncpg.Pool:
    """Return the live pool, raising a clear 503 if it isn't ready."""
    if pool is None:  # pragma: no cover - defensive; startup runs before requests
        raise RuntimeError("Database pool is not initialised")
    return pool


async def get_conn(request: Request) -> AsyncIterator[asyncpg.Connection]:
    """FastAPI dependency: lend a pooled connection for the request scope."""
    db = get_db_pool(request)
    async with db.acquire() as conn:
        yield conn
