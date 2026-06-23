"""POST /transaction — validation + error envelope tests.

These cover the request-shape rules from REQUIREMENTS §5.1 and the error
codes from §10.2. They don't need a real database because validation happens
before any DB access; the dependency override for get_conn is irrelevant
since the handler never reaches it on a 4xx.
"""
from __future__ import annotations

import pytest

from tests.conftest import ALICE, BASE_TXN

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "override, expected_field",
    [
        ({"idempotency_key": "short"}, "idempotency_key"),       # < 8 chars
        ({"idempotency_key": "bad key with spaces!"}, "idempotency_key"),  # bad chars
        ({"amount": 0}, "amount"),                                # not > 0
        ({"amount": -10}, "amount"),
        ({"amount": 1_000_001}, "amount"),                        # over ceiling
        ({"amount": 12.345}, "amount"),                           # > 2 dp
        ({"type": "banana"}, "type"),
        ({"category": "x" * 60}, "category"),                     # too long
    ],
)
async def test_field_validation(client, override, expected_field):
    payload = {**BASE_TXN, **override}
    res = await client.post("/transaction", json=payload)
    assert res.status_code == 400
    body = res.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    fields = {d["field"] for d in body["error"]["details"]}
    assert expected_field in fields


async def test_invalid_category_returns_422_envelope(client):
    # The category allow-list is enforced in the model via field_validator,
    # which surfaces as a 400 here. We assert the canonical code + field.
    res = await client.post("/transaction", json={**BASE_TXN, "category": "gambling"})
    assert res.status_code == 400
    body = res.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert any(d["field"] == "category" for d in body["error"]["details"])


async def test_invalid_uuid_returns_400(client):
    res = await client.post("/transaction", json={**BASE_TXN, "user_id": "not-a-uuid"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_category_is_lowercased_before_storage(client, monkeypatch):
    """Category normalisation happens in the model, so even before the DB
    layer the value reaching the service is lowercased."""
    captured = {}

    async def fake_create(conn, req):
        captured["category"] = req.category
        from app.models import TransactionResponse
        import uuid, datetime
        return TransactionResponse(
            transaction_id=uuid.uuid4(),
            idempotency_key=req.idempotency_key,
            user_id=req.user_id,
            type=req.type,
            amount=req.amount,
            category=req.category,
            description=req.description,
            status="success",
            created_at=datetime.datetime.utcnow().isoformat(),
            is_duplicate=False,
        )

    monkeypatch.setattr("app.routers.transaction.create_transaction", fake_create)
    res = await client.post(
        "/transaction", json={**BASE_TXN, "category": "SALARY", "idempotency_key": "key-case-01"}
    )
    assert res.status_code == 201
    assert captured["category"] == "salary"


async def test_description_stripped_and_max_length(client):
    res = await client.post(
        "/transaction",
        json={**BASE_TXN, "description": "x" * 256, "idempotency_key": "key-desc-01"},
    )
    assert res.status_code == 400
    assert any(d["field"] == "description" for d in res.json()["error"]["details"])


async def test_extra_fields_rejected(client):
    res = await client.post("/transaction", json={**BASE_TXN, "evil": True})
    assert res.status_code == 400
