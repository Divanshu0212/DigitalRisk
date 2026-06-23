"""Per-user sliding-window rate limiter (REQUIREMENTS §9.1).

In-memory implementation backed by an ``asyncio.Lock``-protected dict, keyed
by ``user_id``. We use a true sliding window (list of timestamps trimmed to
the last ``window_seconds``) rather than a fixed window so bursts straddling
a minute boundary cannot double the quota.

This is the documented simplification (A2): production would swap this for a
Redis sorted-set version without changing the public surface —
``RateLimiter.is_limited(user_id, limit, window_seconds)``.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class _WindowState:
    timestamps: list[float] = field(default_factory=list)


class RateLimiter:
    def __init__(self) -> None:
        # One state per user_id; never grows unboundedly because we trim on
        # every check and drop empty windows in ``cleanup()``.
        self._states: dict[str, _WindowState] = defaultdict(_WindowState)
        self._lock = asyncio.Lock()

    async def is_limited(
        self,
        user_id: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> bool:
        """Return True if ``user_id`` has exhausted ``limit`` in the window."""
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            state = self._states[user_id]
            # Drop timestamps that fell out of the window (sliding window).
            state.timestamps = [t for t in state.timestamps if t > cutoff]
            if len(state.timestamps) >= limit:
                return True
            state.timestamps.append(now)
            return False

    async def peek_remaining(
        self,
        user_id: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> int:
        """Non-mutating: how many more requests are allowed right now."""
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            state = self._states.get(user_id)
            if state is None:
                return limit
            recent = [t for t in state.timestamps if t > cutoff]
            return max(0, limit - len(recent))

    async def cleanup(self) -> int:
        """Drop idle windows. Returns the number removed."""
        now = time.monotonic()
        removed = 0
        async with self._lock:
            for user_id in list(self._states.keys()):
                state = self._states[user_id]
                state.timestamps = [t for t in state.timestamps if t > now - 3600]
                if not state.timestamps:
                    del self._states[user_id]
                    removed += 1
        return removed


# Singleton — one limiter for the whole process.
rate_limiter = RateLimiter()
