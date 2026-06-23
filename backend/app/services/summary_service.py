"""Per-user financial summary (REQUIREMENTS §4.2).

The headline aggregates (totals, balance, count, unique_categories) are read
O(1) from the materialised ``user_stats`` row. The ``category_breakdown`` is
computed live from the ``transactions`` table — this is the one place we
aggregate raw rows, kept cheap by the ``(user_id, created_at DESC)`` index.
"""
from __future__ import annotations

from decimal import Decimal

import asyncpg

from app.exceptions import UserNotFoundError
from app.models import CategoryStat, SummaryResponse


_JOIN_USER_STATS = """
SELECT
    u.user_id,
    u.username,
    us.total_credits,
    us.total_debits,
    us.net_balance,
    us.transaction_count,
    us.unique_categories,
    us.last_transaction_at
FROM users u
JOIN user_stats us ON u.user_id = us.user_id
WHERE u.user_id = $1;
"""

_CATEGORY_BREAKDOWN = """
SELECT category, COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total
FROM transactions
WHERE user_id = $1 AND status = 'success'
GROUP BY category
ORDER BY total DESC;
"""


async def get_summary(
    conn: asyncpg.Connection,
    user_id: str,
) -> SummaryResponse:
    row = await conn.fetchrow(_JOIN_USER_STATS, user_id)
    if row is None:
        raise UserNotFoundError(user_id)

    breakdown_rows = await conn.fetch(_CATEGORY_BREAKDOWN, user_id)
    breakdown = {
        r["category"]: CategoryStat(count=r["count"], total=Decimal(r["total"]))
        for r in breakdown_rows
    }

    last = row["last_transaction_at"]
    return SummaryResponse(
        user_id=row["user_id"],
        username=row["username"],
        total_credits=Decimal(row["total_credits"]),
        total_debits=Decimal(row["total_debits"]),
        net_balance=Decimal(row["net_balance"]),
        transaction_count=row["transaction_count"],
        unique_categories=row["unique_categories"],
        last_transaction_at=last.isoformat() if last else None,
        category_breakdown=breakdown,
    )
