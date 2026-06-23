"""Shared pytest fixtures.

The tests use httpx's AsyncClient against the FastAPI app with a dependency
override for ``get_conn`` so they never touch a real database. Validation,
rate-limiting, pagination and error-envelope behaviour can all be exercised
without Postgres: those paths fail fast before the connection is used.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.middleware.rate_limiter import rate_limiter


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Each test starts with a clean limiter window."""
    rate_limiter._states.clear()
    yield
    rate_limiter._states.clear()


class _DummyConn:
    """Stand-in connection for tests that monkeypatch the service layer.
    Real DB calls would never reach this because the service is replaced."""

    async def fetchrow(self, *a, **k):  # pragma: no cover
        return None

    async def fetchval(self, *a, **k):  # pragma: no cover
        return None

    async def fetch(self, *a, **k):  # pragma: no cover
        return []

    async def execute(self, *a, **k):  # pragma: no cover
        return None


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app
    from app.database import get_conn

    app = create_app()
    app.router.lifespan_context = _null_lifespan

    # Override the connection dependency so no DB pool is required.
    async def _override_conn():
        yield _DummyConn()

    app.dependency_overrides[get_conn] = _override_conn

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class _NullCM:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _null_lifespan(app):
    return _NullCM()


# Valid request payload reused across tests.
ALICE = "aaa00000-0000-0000-0000-000000000001"
BASE_TXN = {
    "idempotency_key": "key-0001-test",
    "user_id": ALICE,
    "type": "credit",
    "amount": 250.00,
    "category": "salary",
    "description": "test transaction",
}
