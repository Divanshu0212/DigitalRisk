"""GET /summary/{user_id} — UUID validation + envelope tests."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_invalid_uuid_returns_canonical_error(client):
    res = await client.get("/summary/not-a-uuid")
    assert res.status_code == 400
    body = res.json()
    assert body["error"]["code"] == "INVALID_UUID"
    assert body["error"]["details"][0]["field"] == "user_id"


async def test_summary_shape(client, monkeypatch):
    async def fake_get_summary(conn, user_id):
        from app.models import SummaryResponse, CategoryStat
        from decimal import Decimal
        from uuid import UUID
        return SummaryResponse(
            user_id=UUID(user_id),
            username="alice",
            total_credits=Decimal("5000.00"),
            total_debits=Decimal("1200.00"),
            net_balance=Decimal("3800.00"),
            transaction_count=18,
            unique_categories=4,
            last_transaction_at="2026-06-22T10:30:00Z",
            category_breakdown={
                "salary": CategoryStat(count=3, total=Decimal("3000.00")),
            },
        )

    monkeypatch.setattr("app.routers.summary.get_summary", fake_get_summary)
    res = await client.get("/summary/aaa00000-0000-0000-0000-000000000001")
    assert res.status_code == 200
    body = res.json()
    assert body["username"] == "alice"
    assert body["net_balance"] == "3800.00"
    assert body["category_breakdown"]["salary"]["count"] == 3
