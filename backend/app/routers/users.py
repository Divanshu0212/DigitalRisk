"""GET /users — searchable user listing for the frontend combobox."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.database import get_conn
from app.services.user_service import search_users

router = APIRouter()


@router.get("/users", tags=["users"])
async def list_users(
    search: str = Query("", description="Case-insensitive username or UUID substring"),
    limit: int = Query(50, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_conn),
):
    """Return users matching ``search``. Empty search returns the most active."""
    items = await search_users(conn, search, limit)
    return {"users": items, "count": len(items)}
