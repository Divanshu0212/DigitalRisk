"""User lookup / search (supports the frontend's searchable selector).

Now that we seed ~100 users, a plain ``<select>`` no longer scales. This
service powers ``GET /users?search=``: a case-insensitive, ILIKE-based prefix
search on username (and an exact ``user_id`` match if the caller types a UUID).
Results are capped so a broad search can't return the whole table.
"""
from __future__ import annotations

import asyncpg


_SEARCH_USERS = """
SELECT u.user_id, u.username,
       us.net_balance, us.transaction_count, us.unique_categories
FROM users u
LEFT JOIN user_stats us ON u.user_id = us.user_id
WHERE
    u.username ILIKE '%' || $1 || '%'
    OR ($2::text IS NOT NULL AND u.user_id::text = $2)
ORDER BY
    -- users with activity float to the top of an empty search
    COALESCE(us.transaction_count, 0) DESC,
    u.username ASC
LIMIT $3;
"""


async def search_users(
    conn: asyncpg.Connection,
    search: str,
    limit: int = 50,
) -> list[dict]:
    """Return users whose username matches ``search`` (or whose id matches)."""
    term = (search or "").strip()
    # Detect a UUID so the search box doubles as a "paste-a-UUID" shortcut.
    uuid_term: str | None = None
    if term and len(term) >= 8 and "-" in term:
        try:
            import uuid as _uuid

            _uuid.UUID(term)
            uuid_term = term
        except ValueError:
            uuid_term = None
    rows = await conn.fetch(_SEARCH_USERS, term, uuid_term, limit)
    return [
        {
            "user_id": str(r["user_id"]),
            "username": r["username"],
            "net_balance": float(r["net_balance"]) if r["net_balance"] is not None else 0.0,
            "transaction_count": r["transaction_count"] or 0,
            "unique_categories": r["unique_categories"] or 0,
        }
        for r in rows
    ]
