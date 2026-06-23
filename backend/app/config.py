"""Application settings, loaded from environment via pydantic-settings.

All tunables documented in REQUIREMENTS.md §14.3 live here. The defaults
match the documented assumptions (Section 12) so the app boots with no .env.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Required ---
    database_url: str = "postgresql://postgres:password@localhost:5432/txndb"

    # --- Optional, with documented defaults ---
    allowed_origins: str = "*"
    rate_limit_per_minute: int = 20
    balance_floor: int = -50000
    max_transaction_amount: int = 1_000_000
    ranking_cache_ttl: int = 15  # seconds to memoise /ranking in-process

    # --- Pool sizing (asyncpg) ---
    db_min_size: int = 5
    db_max_size: int = 20
    db_command_timeout: float = 10.0  # kill runaway queries after 10s
    db_max_inactive_connection_lifetime: float = 300.0

    @property
    def cors_origins(self) -> list[str]:
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor — pydantic parses .env once on first call."""
    return Settings()
