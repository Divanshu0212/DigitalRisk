"""Multi-factor leaderboard (REQUIREMENTS §8).

Composite score:

    composite_score = 0.50 * balance_score
                    + 0.25 * activity_score
                    + 0.25 * diversity_score

Each factor is min-max normalised across all users at query time using a
window function, so the whole ranking is computed in a single SQL round-trip
(no Python-side loops). ``NULLIF`` guards against division by zero when every
user shares the same value (epsilon-equivalent).

Tie-breaking: composite_score DESC, last_transaction_at DESC, user_id ASC —
a fully deterministic order (§8.4). We use ``ROW_NUMBER()`` rather than
``RANK()`` for the on-page position because pagination needs a stable single
row per user; the displayed ``rank`` is a global dense rank derived from the
score ordering.
"""
from __future__ import annotations

from decimal import Decimal

import asyncpg

from app.models import RankingEntry, RankingResponse, ScoreBreakdown

# Single CTE pipeline:
#   stats    -> join users + user_stats, add global min/max via OVER ()
#   scored   -> per-user composite + breakdown
#   numbered -> deterministic ROW_NUMBER for pagination
_RANKING_SQL = """
WITH stats AS (
    SELECT
        u.user_id,
        u.username,
        us.net_balance,
        us.transaction_count,
        us.unique_categories,
        us.last_transaction_at,
        MIN(us.net_balance)        OVER () AS min_bal,
        MAX(us.net_balance)        OVER () AS max_bal,
        MIN(us.transaction_count)  OVER () AS min_txn,
        MAX(us.transaction_count)  OVER () AS max_txn,
        MIN(us.unique_categories)  OVER () AS min_cat,
        MAX(us.unique_categories)  OVER () AS max_cat
    FROM users u
    JOIN user_stats us ON u.user_id = us.user_id
),
scored AS (
    SELECT
        user_id,
        username,
        net_balance,
        transaction_count,
        unique_categories,
        last_transaction_at,
        0.50 * COALESCE((net_balance       - min_bal)
            / NULLIF(max_bal - min_bal, 0) * 100, 0) AS balance_score,
        0.25 * COALESCE((transaction_count - min_txn)
            / NULLIF(max_txn - min_txn, 0) * 100, 0) AS activity_score,
        0.25 * COALESCE((unique_categories - min_cat)
            / NULLIF(max_cat - min_cat, 0) * 100, 0) AS diversity_score
    FROM stats
),
final AS (
    SELECT
        *,
        (balance_score + activity_score + diversity_score) AS composite_score
    FROM scored
),
numbered AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            ORDER BY composite_score DESC,
                     last_transaction_at DESC NULLS LAST,
                     user_id ASC
        ) AS rn
    FROM final
)
SELECT
    rn AS rank,
    user_id,
    username,
    net_balance,
    transaction_count,
    unique_categories,
    ROUND(composite_score::numeric, 2) AS composite_score,
    ROUND(balance_score::numeric,  2) AS balance_score,
    ROUND(activity_score::numeric, 2) AS activity_score,
    ROUND(diversity_score::numeric, 2) AS diversity_score
FROM numbered
ORDER BY rn
LIMIT $1 OFFSET $2;
"""

_COUNT_SQL = "SELECT COUNT(*) FROM user_stats;"


async def get_ranking(
    conn: asyncpg.Connection,
    page: int,
    limit: int,
) -> RankingResponse:
    offset = (page - 1) * limit
    rows = await conn.fetch(_RANKING_SQL, limit, offset)
    total = await conn.fetchval(_COUNT_SQL)

    entries = [
        RankingEntry(
            rank=r["rank"],
            user_id=r["user_id"],
            username=r["username"],
            net_balance=Decimal(r["net_balance"]),
            transaction_count=r["transaction_count"],
            unique_categories=r["unique_categories"],
            composite_score=float(r["composite_score"]),
            score_breakdown=ScoreBreakdown(
                balance_score=float(r["balance_score"]),
                activity_score=float(r["activity_score"]),
                diversity_score=float(r["diversity_score"]),
            ),
        )
        for r in rows
    ]

    return RankingResponse(
        page=page,
        limit=limit,
        total_users=total,
        ranking=entries,
    )
