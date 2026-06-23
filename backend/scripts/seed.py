"""Seed ~100 users + ~1000 diverse transactions (REQUIREMENTS §12.2, expanded).

Two ways to run:
  1. Automatically on app startup — the lifespan in ``main.py`` calls
     ``run_seed()`` after migration if the DB is empty. No subprocess needed.
  2. Manually: ``python scripts/seed.py`` (uses its own DB connection).

The first five users are the canonical seed identities from the spec
(alice…eve). The remaining ~95 are generated with realistic-looking
usernames so the leaderboard, summary views and the searchable selector
have meaningful data to show.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import sys
import uuid as _uuid
from pathlib import Path

import asyncpg

from app.config import get_settings
from app.models import ALLOWED_CATEGORIES

logger = logging.getLogger("seed")

# ---------------------------------------------------------------------------
# Canonical spec users (aaa.. bbb.. etc.) — keep their documented IDs.
# ---------------------------------------------------------------------------
CANONICAL_USERS = [
    ("alice", "aaa00000-0000-0000-0000-000000000001"),
    ("bob",   "bbb00000-0000-0000-0000-000000000002"),
    ("carol", "ccc00000-0000-0000-0000-000000000003"),
    ("dave",  "ddd00000-0000-0000-0000-000000000004"),
    ("eve",   "eee00000-0000-0000-0000-000000000005"),
]

# How many *additional* generated users to create (100 total with canonical).
EXTRA_USER_COUNT = 95

# Name pools for generated usernames — keeps them human-readable & searchable.
FIRST = [
    "alex", "sam", "jordan", "casey", "taylor", "morgan", "riley", "jamie",
    "avery", "quinn", "reese", "parker", "rowan", "sage", "finn", "nico",
    "max", "kai", "leo", "nova", "iris", "luna", "ruby", "milo", "ezra",
    "aria", "zoe", "ethan", "nina", "omar", "priya", "yuki", "diego", "lena",
    "felix", "maya", "oscar", "tara", "ivan", "nora", "hugo", "lila", "arjun",
]
LAST = [
    "chen", "patel", "garcia", "kim", "nguyen", "silva", "khan", "singh",
    "rossi", "muller", "dubois", "nowak", "jensen", "hassan", "ahmed",
    "tanaka", "park", "li", "wagner", "ruiz", "costa", "shah", "lee",
    "fernandez", "schmidt",
]


def _gen_username(idx: int, rng: random.Random) -> str:
    f = rng.choice(FIRST)
    l = rng.choice(LAST)
    fmt = idx % 3
    if fmt == 0:
        return f"{f}.{l}"
    if fmt == 1:
        return f"{f}_{l}{idx:02d}"
    return f"{l}{f}{idx}"


def _profile_for(rank: int, total: int, rng: random.Random) -> dict:
    """rank=0 is the most active user, rank=total-1 the least."""
    base = 1.0 - (rank / max(total, 1))
    credits = max(2, int(rng.uniform(15, 40) * base))
    debits = max(0, int(rng.uniform(3, 15) * base))
    cats = rng.randint(2, len(ALLOWED_CATEGORIES))
    return {"credits": credits, "debits": debits, "cats": cats}


async def _ensure_users(conn: asyncpg.Connection) -> list[tuple[str, str]]:
    """Insert the canonical + generated users; return (username, user_id)."""
    rng = random.Random(42)
    rows: list[tuple[str, str]] = list(CANONICAL_USERS)

    seen = {u for u, _ in rows}
    generated: list[tuple[str, str]] = []
    idx = 0
    while len(generated) < EXTRA_USER_COUNT:
        idx += 1
        name = _gen_username(idx, rng)
        if name in seen:
            continue
        seen.add(name)
        digest = hashlib.md5(f"txnrank:{name}".encode()).digest()
        uid = str(_uuid.UUID(bytes=digest[:16], version=4))
        generated.append((name, uid))
    rows.extend(generated)

    await conn.executemany(
        "INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        [(uid, name) for name, uid in rows],
    )
    return rows


async def _bulk_insert(conn: asyncpg.Connection, users: list[tuple[str, str]]) -> int:
    rng = random.Random(7)
    txn_rows: list[tuple] = []
    idx = 0
    total = len(users)
    for rank, (username, uid) in enumerate(users):
        profile = _profile_for(rank, total, rng)
        cats = rng.sample(ALLOWED_CATEGORIES, min(profile["cats"], len(ALLOWED_CATEGORIES)))
        for _ in range(profile["credits"]):
            idx += 1
            txn_rows.append((
                f"seed-txn-{idx:05d}",
                uid, "credit",
                round(rng.uniform(80, 4500), 2),
                rng.choice(cats),
                "seed credit",
            ))
        for _ in range(profile["debits"]):
            idx += 1
            txn_rows.append((
                f"seed-txn-{idx:05d}",
                uid, "debit",
                round(rng.uniform(15, 900), 2),
                rng.choice(cats),
                "seed debit",
            ))

    await conn.executemany(
        """
        INSERT INTO transactions (idempotency_key, user_id, type, amount, category, description)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        txn_rows,
    )
    return len(txn_rows)


async def _recompute_stats(conn: asyncpg.Connection) -> None:
    """Rebuild user_stats from the transactions table."""
    await conn.execute(
        """
        INSERT INTO user_stats (
            user_id, total_credits, total_debits, net_balance,
            transaction_count, unique_categories, last_transaction_at, updated_at
        )
        SELECT
            t.user_id,
            COALESCE(SUM(CASE WHEN type = 'credit' THEN amount ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN type = 'debit'  THEN amount ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN type = 'credit' THEN amount ELSE -amount END), 0),
            COUNT(*),
            COUNT(DISTINCT category),
            MAX(created_at),
            NOW()
        FROM transactions t
        WHERE t.status = 'success'
        GROUP BY t.user_id
        ON CONFLICT (user_id) DO UPDATE SET
            total_credits       = EXCLUDED.total_credits,
            total_debits        = EXCLUDED.total_debits,
            net_balance         = EXCLUDED.net_balance,
            transaction_count   = EXCLUDED.transaction_count,
            unique_categories   = EXCLUDED.unique_categories,
            last_transaction_at = EXCLUDED.last_transaction_at,
            updated_at          = NOW()
        """
    )


async def run_seed(conn: asyncpg.Connection | None = None) -> None:
    """Core seed logic. Accepts an external connection (pooled) or opens its own.

    This is the function called by ``main.py`` lifespan after migration.
    """
    own_conn = False
    if conn is None:
        # Standalone invocation — open our own connection.
        settings = get_settings()
        url = os.getenv("DATABASE_URL", settings.database_url)
        conn = await asyncpg.connect(dsn=url)
        own_conn = True

    try:
        users = await _ensure_users(conn)
        logger.info(
            "Ensured %d users (%d canonical + %d generated)",
            len(users), len(CANONICAL_USERS), EXTRA_USER_COUNT,
        )

        n = await _bulk_insert(conn, users)
        logger.info("Inserted %d seed transactions", n)

        await _recompute_stats(conn)
        logger.info("Recomputed user_stats aggregates")

        rows = await conn.fetch(
            """
            SELECT u.username, us.net_balance, us.transaction_count, us.unique_categories
            FROM users u JOIN user_stats us ON u.user_id = us.user_id
            ORDER BY us.net_balance DESC
            LIMIT 10
            """
        )
        logger.info("Top 10 by net balance:")
        for r in rows:
            logger.info(
                "  %-16s balance=%11s  txns=%4d  cats=%d",
                r["username"], float(r["net_balance"]),
                r["transaction_count"], r["unique_categories"],
            )
    finally:
        if own_conn:
            await conn.close()


async def main() -> None:
    """CLI entry point: ``python scripts/seed.py``."""
    await run_seed()


if __name__ == "__main__":
    asyncio.run(main())
