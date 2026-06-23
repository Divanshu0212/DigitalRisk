"""Tiny in-process TTL cache for read-heavy endpoints.

The ranking is global and changes only when a transaction lands. Recomputing
the composite-score SQL on every page-1 hit is wasteful, so we memoise the
serialised response for ``ttl`` seconds (default 15s from settings). A write
to the transaction endpoint invalidates the cache immediately via ``clear()``.

Why not Redis / functools.lru_cache?
  - Redis would be the prod answer but adds infra (documented in README).
  - ``lru_cache`` has no TTL, so stale data would linger until restart.
This hand-rolled TTL is monotonic-clock based (no drift on wall-clock
changes) and is async-safe via an ``asyncio.Lock``.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class _Entry(Generic[V]):
    value: V
    expires_at: float


class TTLCache(Generic[K, V]):
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._store: dict[K, _Entry[V]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: K) -> V | None:
        now = time.monotonic()
        async with self._lock:
            entry = self._store.get(key)
            if entry is None or entry.expires_at <= now:
                if entry is not None:
                    # Lazy eviction of the stale slot.
                    self._store.pop(key, None)
                return None
            return entry.value

    async def set(self, key: K, value: V) -> None:
        now = time.monotonic()
        async with self._lock:
            self._store[key] = _Entry(value=value, expires_at=now + self._ttl)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def get_or_compute(self, key: K, compute: Callable[[], Awaitable[V]]) -> V:
        """Read-through: return cached value or compute, cache and return."""
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await compute()
        await self.set(key, value)
        return value
