"""Transaction creation: idempotency, locking, atomic stats update.

Flow (REQUIREMENTS §3.4, §6.2, §7.2):
  1. Look up user (404 if missing) and acquire a row lock on user_stats.
  2. INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING ...
       - 0 rows => duplicate -> fetch original, return is_duplicate=True.
       - 1 row  => new -> update user_stats inside the same txn.
  3. COMMIT releases the SELECT FOR UPDATE lock.

The lock + unique index together guarantee exactly-once accounting even if
two identical requests race: PostgreSQL serialises both at the constraint,
the loser sees no RETURNING row and skips the stats mutation entirely.
"""
from __future__ import annotations

import logging
from decimal import Decimal

import asyncpg

from app.config import get_settings
from app.exceptions import (
    InsufficientFundsError,
    UserNotFoundError,
)
from app.models import TransactionRequest, TransactionResponse
from app.middleware.rate_limiter import rate_limiter
from app.middleware.ttl_cache import TTLCache

logger = logging.getLogger(__name__)

# Ranking result is invalidated on every successful write (see §8 ranking).
ranking_cache: TTLCache[tuple[int, int], dict] | None = None


def invalidate_ranking_cache() -> None:
    """Called after a write so /ranking reflects fresh data immediately."""
    if ranking_cache is not None:
        # Fire-and-forget; safe to ignore since clear() is best-effort.
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(ranking_cache.clear())
        else:  # pragma: no cover
            ranking_cache._store.clear()


# SQL ------------------------------------------------------------------------

_LOCK_AND_LOAD = """
SELECT us.user_id
FROM user_stats us
WHERE us.user_id = $1
FOR UPDATE;
"""

_INSERT_TXN = """
INSERT INTO transactions (idempotency_key, user_id, type, amount, category, description)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING transaction_id, created_at, status;
"""

_UPDATE_STATS_CREDIT = """
UPDATE user_stats
SET
    total_credits     = total_credits + $2,
    net_balance       = net_balance + $2,
    transaction_count = transaction_count + 1,
    unique_categories = (
        SELECT COUNT(DISTINCT category) FROM transactions WHERE user_id = $1
    ),
    last_transaction_at = NOW(),
    updated_at          = NOW()
WHERE user_id = $1
RETURNING net_balance;
"""

_UPDATE_STATS_DEBIT = """
UPDATE user_stats
SET
    total_debits      = total_debits + $2,
    net_balance       = net_balance - $2,
    transaction_count = transaction_count + 1,
    unique_categories = (
        SELECT COUNT(DISTINCT category) FROM transactions WHERE user_id = $1
    ),
    last_transaction_at = NOW(),
    updated_at          = NOW()
WHERE user_id = $1
RETURNING net_balance;
"""

_FETCH_EXISTING = """
SELECT transaction_id, user_id, type, amount, category, description, status, created_at
FROM transactions
WHERE idempotency_key = $1;
"""


async def create_transaction(
    conn: asyncpg.Connection,
    req: TransactionRequest,
) -> TransactionResponse:
    """Persist a transaction with full idempotency + locking guarantees."""
    settings = get_settings()
    user_id_str = str(req.user_id)

    # --- Rate limit (§9.1): 20 req/user/minute, sliding window ----------
    if await rate_limiter.is_limited(
        user_id_str,
        limit=settings.rate_limit_per_minute,
        window_seconds=60,
    ):
        from app.exceptions import RateLimitedError

        raise RateLimitedError(retry_after=60)

    async with conn.transaction():
        # --- Lock the user's stats row for the whole txn (§6.2) ---------
        # The lock also implicitly validates the user exists; a missing
        # user_stats row means the user is unknown.
        locked = await conn.fetchval(_LOCK_AND_LOAD, user_id_str)
        if locked is None:
            # Confirm it's not a missing-stats-but-existing-user scenario.
            exists = await conn.fetchval(
                "SELECT 1 FROM users WHERE user_id = $1", user_id_str
            )
            if not exists:
                raise UserNotFoundError(user_id_str)
            # User exists but has no stats row yet — create one inside the
            # same txn so the rest of the flow works.
            await conn.execute(
                """
                INSERT INTO user_stats (user_id)
                VALUES ($1)
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id_str,
            )
            await conn.fetchval(_LOCK_AND_LOAD, user_id_str)

        # --- Idempotent insert (§7.2) -----------------------------------
        inserted = await conn.fetchrow(
            _INSERT_TXN,
            req.idempotency_key,
            user_id_str,
            req.type,
            req.amount,
            req.category,
            req.description,
        )

        if inserted is None:
            # Duplicate idempotency key -> replay the original result.
            existing = await conn.fetchrow(_FETCH_EXISTING, req.idempotency_key)
            return TransactionResponse(
                transaction_id=existing["transaction_id"],
                idempotency_key=req.idempotency_key,
                user_id=existing["user_id"],
                type=existing["type"],
                amount=Decimal(existing["amount"]),
                category=existing["category"],
                description=existing["description"],
                status=existing["status"],
                created_at=existing["created_at"].isoformat(),
                is_duplicate=True,
            )

        # --- Update aggregates atomically (§3.3, §5.2) ------------------
        signed = req.amount if req.type == "credit" else -req.amount
        if req.type == "debit":
            new_balance = await conn.fetchval(_UPDATE_STATS_DEBIT, user_id_str, req.amount)
            # Reject debits that breach the floor (§5.2, §9.5).
            if new_balance is not None and Decimal(new_balance) < Decimal(settings.balance_floor):
                # Raising inside the txn aborts both the INSERT and the
                # UPDATE, so the user is not charged and the idempotency
                # key is freed for a corrected retry.
                raise InsufficientFundsError(float(new_balance), float(settings.balance_floor))
        else:
            await conn.fetchval(_UPDATE_STATS_CREDIT, user_id_str, req.amount)

    # Cache invalidation so /ranking reflects the new transaction.
    invalidate_ranking_cache()

    return TransactionResponse(
        transaction_id=inserted["transaction_id"],
        idempotency_key=req.idempotency_key,
        user_id=req.user_id,
        type=req.type,
        amount=req.amount,
        category=req.category,
        description=req.description,
        status=inserted["status"],
        created_at=inserted["created_at"].isoformat(),
        is_duplicate=False,
    )
