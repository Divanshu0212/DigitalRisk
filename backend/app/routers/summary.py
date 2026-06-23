"""GET /summary/{user_id} (REQUIREMENTS §4.2)."""
from __future__ import annotations

import uuid

import asyncpg
from fastapi import APIRouter, Depends

from app.database import get_conn
from app.exceptions import InvalidUUIDError
from app.models import SummaryResponse
from app.services.summary_service import get_summary

router = APIRouter()


@router.get(
    "/summary/{user_id}",
    response_model=SummaryResponse,
)
async def get_user_summary(user_id: str, conn: asyncpg.Connection = Depends(get_conn)):
    # Validate the path param as a UUID4 here (not via the path type) so we
    # can raise the canonical INVALID_UUID error code instead of FastAPI's
    # generic 422.
    try:
        uuid.UUID(user_id)
    except (ValueError, AttributeError):
        raise InvalidUUIDError(user_id)
    return await get_summary(conn, user_id)
