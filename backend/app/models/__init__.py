"""Pydantic request/response models.

Field-level validation runs before any DB access (REQUIREMENTS §5.1). Where
a rule is purely about the request shape (UUID, enum, decimal precision) we
keep it in the model so it fails fast with a 400 VALIDATION_ERROR. Semantic
rules that depend on DB state (user existence, category allow-list) are
checked in the service layer and raise the more specific codes (404, 422).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Pydantic doesn't export a non-version-restricted "UUID" symbol by name, so
# we use uuid.UUID directly as the field type. This accepts any well-formed
# UUID, including the non-v4 seed IDs from REQUIREMENTS.md §12.2.
import uuid

UUID4 = uuid.UUID

# The canonical allow-list shared between the request model, the category
# validator and the seed script (REQUIREMENTS §4.1).
ALLOWED_CATEGORIES: tuple[str, ...] = (
    "salary",
    "freelance",
    "investment",
    "transfer",
    "food",
    "utilities",
    "rent",
    "entertainment",
    "healthcare",
    "education",
    "other",
)


class TransactionRequest(BaseModel):
    """POST /transaction body (REQUIREMENTS §4.1, §5.1)."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(..., min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9\-]+$")
    user_id: UUID4
    type: Literal["credit", "debit"]
    amount: Decimal = Field(..., gt=0, le=1_000_000, decimal_places=2)
    category: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=255)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        lowered = v.strip().lower()
        if lowered not in ALLOWED_CATEGORIES:
            # Raise a plain ValueError so Pydantic surfaces a 400 here; the
            # service-layer re-raises InvalidCategoryError (422) when a
            # caller somehow bypasses the model.
            raise ValueError(
                f"Category must be one of: {', '.join(ALLOWED_CATEGORIES)}"
            )
        return lowered

    @field_validator("amount")
    @classmethod
    def validate_amount_precision(cls, v: Decimal) -> Decimal:
        # Guard against floating-point tricks like 0.001 slipping through.
        if v.as_tuple().exponent < -2:
            raise ValueError("Amount must have at most 2 decimal places")
        return v

    @field_validator("description")
    @classmethod
    def strip_description(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else v


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TransactionResponse(BaseModel):
    transaction_id: UUID4
    idempotency_key: str
    user_id: UUID4
    type: Literal["credit", "debit"]
    amount: Decimal
    category: str
    description: Optional[str] = None
    status: Literal["success", "failed"] = "success"
    created_at: str  # ISO-8601 UTC string
    is_duplicate: bool = False


class CategoryStat(BaseModel):
    count: int
    total: Decimal


class SummaryResponse(BaseModel):
    user_id: UUID4
    username: str
    total_credits: Decimal
    total_debits: Decimal
    net_balance: Decimal
    transaction_count: int
    unique_categories: int
    last_transaction_at: Optional[str] = None
    category_breakdown: dict[str, CategoryStat]


class ScoreBreakdown(BaseModel):
    balance_score: float
    activity_score: float
    diversity_score: float


class RankingEntry(BaseModel):
    rank: int
    user_id: UUID4
    username: str
    net_balance: Decimal
    transaction_count: int
    unique_categories: int
    composite_score: float
    score_breakdown: ScoreBreakdown


class RankingResponse(BaseModel):
    page: int
    limit: int
    total_users: int
    ranking: list[RankingEntry]
