"""POST /transaction (REQUIREMENTS §4.1)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.database import get_conn
import asyncpg

from app.models import TransactionRequest, TransactionResponse
from app.services.transaction_service import create_transaction

router = APIRouter()


@router.post(
    "/transaction",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "Duplicate idempotency key replayed"},
        400: {"description": "Validation error"},
        402: {"description": "Insufficient funds (balance floor breach)"},
        404: {"description": "User not found"},
        422: {"description": "Invalid category"},
        429: {"description": "Rate limited"},
    },
)
async def post_transaction(
    req: TransactionRequest,
    conn: asyncpg.Connection = Depends(get_conn),
):
    """Create a transaction. 201 on new, 200 on idempotency replay."""
    resp = await create_transaction(conn, req)
    if resp.is_duplicate:
        # Replay -> 200 (REQUIREMENTS §4.1 / §10.2).
        return JSONResponse(status_code=200, content=resp.model_dump(mode="json"))
    # New -> 201; FastAPI renders the response_model.
    return resp
