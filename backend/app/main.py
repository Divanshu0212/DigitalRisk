"""FastAPI application entry point.

Wires: lifespan (DB pool), CORS, exception handlers, routers, and an access
log. The lifespan context also runs the schema migration on startup so a
fresh ``docker-compose up`` is immediately usable (REQUIREMENTS §14.1).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import close_pool, init_pool
from app.exceptions import register_exception_handlers
from app.middleware.rate_limiter import rate_limiter
from app.routers import ranking, summary, transaction, users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")


_MIGRATION_FILE = Path(__file__).resolve().parent.parent / "migrations" / "001_initial_schema.sql"


async def _apply_migrations_if_requested() -> None:
    """Run the schema migration on boot when AUTO_MIGRATE != '0'.

    Convenient for local dev / docker-compose. Disabled in tests to avoid
    clobbering an existing DB. Skipped silently if the file is absent.
    """
    if os.getenv("AUTO_MIGRATE", "1") == "0":
        return
    if not _MIGRATION_FILE.exists():
        logger.warning("Migration file not found at %s; skipping", _MIGRATION_FILE)
        return
    from app.database import pool as _pool

    if _pool is None:
        return
    sql = _MIGRATION_FILE.read_text()
    async with _pool.acquire() as conn:
        await conn.execute(sql)
    logger.info("Applied migration %s", _MIGRATION_FILE.name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    await init_pool()
    await _apply_migrations_if_requested()
    logger.info("Transaction & Ranking Service ready")
    yield
    # --- Shutdown ---
    await close_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Transaction & Ranking Service",
        version="1.0.0",
        description=(
            "Financial transactions, per-user summaries, and a multi-factor "
            "leaderboard. Built per the REQUIREMENTS.md specification."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(transaction.router, tags=["transactions"])
    app.include_router(summary.router, tags=["summary"])
    app.include_router(ranking.router, tags=["ranking"])
    app.include_router(users.router, tags=["users"])

    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        """Liveness probe used by docker-compose / deploy platforms."""
        return {"status": "ok"}

    return app


app = create_app()
