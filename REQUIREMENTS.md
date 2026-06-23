# Backend Assignment — Requirements Document

**Project:** Transaction & Ranking Service  
**Stack:** Python (FastAPI) · PostgreSQL · React (Frontend)  
**Author:** Divanshu  
**Version:** 1.0

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Database Schema](#3-database-schema)
4. [API Specifications](#4-api-specifications)
   - [POST /transaction](#41-post-transaction)
   - [GET /summary/:userId](#42-get-summaryuserid)
   - [GET /ranking](#43-get-ranking)
5. [Validation Rules](#5-validation-rules)
6. [Concurrency & Data Consistency](#6-concurrency--data-consistency)
7. [Idempotency & Duplicate Prevention](#7-idempotency--duplicate-prevention)
8. [Ranking Logic](#8-ranking-logic)
9. [Abuse & Manipulation Prevention](#9-abuse--manipulation-prevention)
10. [Error Handling](#10-error-handling)
11. [Frontend Requirements](#11-frontend-requirements)
12. [Assumptions & Mock Data](#12-assumptions--mock-data)
13. [Project Structure](#13-project-structure)
14. [Setup & Running](#14-setup--running)

---

## 1. Project Overview

This service manages financial transactions for users, computes per-user summaries, and exposes a multi-factor leaderboard ranking. The system is designed to be safe under concurrent load, resistant to duplicate processing, and resilient against basic ranking manipulation.

**Core capabilities:**

- Accept and persist user transactions with full validation
- Prevent double-processing of the same request via idempotency keys
- Handle simultaneous requests without race conditions using database-level locking
- Compute per-user financial summaries on demand
- Produce a fair, multi-factor ranking that cannot be gamed by volume alone

---

## 2. System Architecture

```
┌──────────────┐        HTTPS          ┌──────────────────────────────┐
│              │ ───────────────────▶  │         FastAPI Backend        │
│   React      │                       │                                │
│   Frontend   │ ◀───────────────────  │  ┌──────────┐  ┌──────────┐  │
│  (Deployed)  │        JSON           │  │  Routers │  │ Services │  │
└──────────────┘                       │  └──────────┘  └──────────┘  │
                                       │         │                      │
                                       │  ┌──────▼──────────────────┐  │
                                       │  │     asyncpg Pool         │  │
                                       │  └──────────────────────────┘  │
                                       └──────────────┬───────────────┘
                                                      │
                                              ┌───────▼───────┐
                                              │  PostgreSQL DB │
                                              └───────────────┘
```

**Technology choices:**

| Component | Technology | Reason |
|-----------|-----------|--------|
| Backend framework | FastAPI | Async-native, auto OpenAPI docs, Pydantic validation |
| Async DB driver | asyncpg | Non-blocking PostgreSQL driver for FastAPI |
| Database | PostgreSQL | ACID transactions, `SELECT FOR UPDATE`, advisory locks |
| Frontend | React + Vite | Lightweight, fast to build |
| Deployment | Railway / Render (backend) · Vercel (frontend) | Free tier, supports PostgreSQL |

---

## 3. Database Schema

### 3.1 `users` table

Stores registered users and their aggregate stats. Aggregate columns are updated atomically alongside each transaction to avoid expensive `SUM` queries on the ranking endpoint.

```sql
CREATE TABLE users (
    user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      TEXT NOT NULL UNIQUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 3.2 `transactions` table

Every accepted transaction is written here. The `idempotency_key` column enforces exactly-once processing at the database level. The `(user_id, created_at)` composite index supports fast summary lookups.

```sql
CREATE TABLE transactions (
    transaction_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key  TEXT NOT NULL UNIQUE,          -- client-supplied dedup key
    user_id          UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    type             TEXT NOT NULL CHECK (type IN ('credit', 'debit')),
    amount           NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    category         TEXT NOT NULL,
    description      TEXT,
    status           TEXT NOT NULL DEFAULT 'success' CHECK (status IN ('success', 'failed')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_transactions_user_created ON transactions(user_id, created_at DESC);
CREATE UNIQUE INDEX idx_transactions_idempotency ON transactions(idempotency_key);
```

### 3.3 `user_stats` table

Maintained as a **materialised summary** updated inside the same transaction as every write. This gives O(1) reads for `/summary` and `/ranking` instead of full-table aggregations.

```sql
CREATE TABLE user_stats (
    user_id              UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    total_credits        NUMERIC(18, 2) NOT NULL DEFAULT 0,
    total_debits         NUMERIC(18, 2) NOT NULL DEFAULT 0,
    net_balance          NUMERIC(18, 2) NOT NULL DEFAULT 0,   -- credits - debits
    transaction_count    INTEGER NOT NULL DEFAULT 0,
    unique_categories    INTEGER NOT NULL DEFAULT 0,          -- for ranking diversity factor
    last_transaction_at  TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 3.4 Data Flow

```
Client sends POST /transaction
        │
        ▼
Check idempotency_key in transactions table
        │
   ┌────┴────┐
  dup?      new
   │         │
return       BEGIN TRANSACTION
cached         │
response       ├─ INSERT INTO transactions
               ├─ UPDATE user_stats  (atomic with SELECT FOR UPDATE on user_stats row)
               └─ COMMIT
```

---

## 4. API Specifications

### 4.1 POST /transaction

Creates a new financial transaction for a user.

**Endpoint:** `POST /transaction`  
**Content-Type:** `application/json`

#### Request Body

```json
{
  "idempotency_key": "txn-abc-123",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "credit",
  "amount": 250.00,
  "category": "salary",
  "description": "Monthly salary credit"
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `idempotency_key` | string | Yes | 8–128 chars, alphanumeric + hyphens only |
| `user_id` | UUID string | Yes | Must exist in `users` table |
| `type` | string | Yes | Must be `"credit"` or `"debit"` |
| `amount` | number | Yes | > 0, max 2 decimal places, ≤ 1,000,000 per transaction |
| `category` | string | Yes | 1–50 chars, letters/numbers/hyphens, from allowed list |
| `description` | string | No | Max 255 chars |

**Allowed categories:** `salary`, `freelance`, `investment`, `transfer`, `food`, `utilities`, `rent`, `entertainment`, `healthcare`, `education`, `other`

#### Response — 201 Created (new transaction)

```json
{
  "transaction_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "idempotency_key": "txn-abc-123",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "credit",
  "amount": 250.00,
  "category": "salary",
  "description": "Monthly salary credit",
  "status": "success",
  "created_at": "2026-06-22T10:30:00Z",
  "is_duplicate": false
}
```

#### Response — 200 OK (duplicate idempotency key — replayed)

Same body as above, with `"is_duplicate": true`. The original transaction data is returned; no second write occurs.

#### Error Responses

| Status | Code | Scenario |
|--------|------|----------|
| 400 | `VALIDATION_ERROR` | Missing/invalid fields |
| 404 | `USER_NOT_FOUND` | `user_id` doesn't exist |
| 422 | `INVALID_CATEGORY` | Category not in allowed list |
| 429 | `RATE_LIMITED` | > 20 requests / user / minute |
| 500 | `INTERNAL_ERROR` | Unexpected DB or server error |

---

### 4.2 GET /summary/:userId

Returns a financial summary for a specific user.

**Endpoint:** `GET /summary/{user_id}`

#### Response — 200 OK

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice",
  "total_credits": 5000.00,
  "total_debits": 1200.00,
  "net_balance": 3800.00,
  "transaction_count": 18,
  "unique_categories": 5,
  "last_transaction_at": "2026-06-22T10:30:00Z",
  "category_breakdown": {
    "salary": { "count": 3, "total": 3000.00 },
    "freelance": { "count": 5, "total": 2000.00 },
    "food": { "count": 6, "total": 800.00 },
    "utilities": { "count": 4, "total": 400.00 }
  }
}
```

`category_breakdown` is computed live from the `transactions` table (only for the summary endpoint; ranking uses the pre-aggregated `user_stats`).

#### Error Responses

| Status | Code | Scenario |
|--------|------|----------|
| 400 | `INVALID_UUID` | `user_id` is not a valid UUID |
| 404 | `USER_NOT_FOUND` | No user with that ID |

---

### 4.3 GET /ranking

Returns a paginated leaderboard ranked by a multi-factor score.

**Endpoint:** `GET /ranking`

#### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | 1 | Page number (1-indexed) |
| `limit` | integer | 10 | Results per page (max 50) |

#### Response — 200 OK

```json
{
  "page": 1,
  "limit": 10,
  "total_users": 143,
  "ranking": [
    {
      "rank": 1,
      "user_id": "550e8400-e29b-41d4-a716-446655440000",
      "username": "alice",
      "net_balance": 3800.00,
      "transaction_count": 18,
      "unique_categories": 5,
      "composite_score": 91.4,
      "score_breakdown": {
        "balance_score": 45.2,
        "activity_score": 22.1,
        "diversity_score": 24.1
      }
    }
  ]
}
```

---

## 5. Validation Rules

All validation is performed by Pydantic models before any database access.

### 5.1 Field-Level Rules

```python
class TransactionRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=8, max_length=128, pattern=r'^[a-zA-Z0-9\-]+$')
    user_id: UUID4
    type: Literal["credit", "debit"]
    amount: Decimal = Field(..., gt=0, le=1_000_000, decimal_places=2)
    category: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=255)

    @field_validator("category")
    def validate_category(cls, v):
        allowed = {"salary","freelance","investment","transfer","food",
                   "utilities","rent","entertainment","healthcare","education","other"}
        if v.lower() not in allowed:
            raise ValueError(f"Category must be one of: {', '.join(sorted(allowed))}")
        return v.lower()

    @field_validator("amount")
    def validate_amount_precision(cls, v):
        # Guard against floating-point tricks like 0.001 slipping through
        if v.as_tuple().exponent < -2:
            raise ValueError("Amount must have at most 2 decimal places")
        return v
```

### 5.2 Cross-Field Rules

- A `debit` transaction that would push a user's balance below `-50,000` is rejected with `402 INSUFFICIENT_FUNDS`. This threshold is a documented assumption (see Section 12).
- `amount` is stored as `NUMERIC(18,2)` in PostgreSQL — no floating-point drift.

---

## 6. Concurrency & Data Consistency

### 6.1 The Race Condition Problem

Two concurrent credits for the same user could both read `net_balance = 100`, both add `50`, and both write `150` — losing one update (lost update anomaly).

### 6.2 Solution: `SELECT FOR UPDATE` on `user_stats`

Every write to `user_stats` is preceded by a row-level lock:

```sql
BEGIN;

-- Lock this user's stats row for the duration of the transaction
SELECT * FROM user_stats WHERE user_id = $1 FOR UPDATE;

-- Safe to update — no other session can modify this row until COMMIT
UPDATE user_stats
SET
    total_credits     = total_credits + $2,
    net_balance       = net_balance + $2,
    transaction_count = transaction_count + 1,
    updated_at        = NOW()
WHERE user_id = $1;

INSERT INTO transactions (...) VALUES (...);

COMMIT;
```

This serialises concurrent writes to the same user without locking unrelated rows, giving good throughput across different users while maintaining consistency per user.

### 6.3 asyncpg Connection Pool

```python
pool = await asyncpg.create_pool(
    dsn=settings.DATABASE_URL,
    min_size=5,
    max_size=20,
    command_timeout=10,       # kill runaway queries after 10 s
    max_inactive_connection_lifetime=300,
)
```

All route handlers acquire a connection from the pool using `async with pool.acquire() as conn`, ensuring the event loop is never blocked.

---

## 7. Idempotency & Duplicate Prevention

### 7.1 Client Contract

Every `POST /transaction` request **must** include an `idempotency_key` — a client-generated unique string (e.g., UUID or `{userId}-{timestamp}-{nonce}`). The key is valid for **24 hours** from first use; replaying the same key within 24 hours returns the original result without re-processing.

### 7.2 Server-Side Enforcement

The `idempotency_key` column has a `UNIQUE` constraint. The insert uses `ON CONFLICT DO NOTHING` and then checks rows affected:

```sql
INSERT INTO transactions (idempotency_key, user_id, type, amount, category, description)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING transaction_id;
```

If `RETURNING` yields no row, the key already exists — the existing transaction is fetched and returned with `is_duplicate: true`. The `user_stats` update is skipped entirely.

### 7.3 Why This Is Safe Under Concurrency

Two simultaneous requests with the same `idempotency_key` will race on the `UNIQUE` constraint. PostgreSQL guarantees only one `INSERT` succeeds. The loser gets 0 rows from `RETURNING`, hits the duplicate path, and returns the original result. No partial writes, no double-credits.

---

## 8. Ranking Logic

### 8.1 Why a Single Factor Is Insufficient

Ranking purely by `net_balance` rewards users who made one large deposit and nothing else. Ranking purely by `transaction_count` rewards users who spam tiny transactions. Either approach is gameable and does not reflect genuine engagement.

### 8.2 Composite Score Formula

The ranking score is computed from three normalised factors:

```
composite_score = (balance_score × 0.5) + (activity_score × 0.25) + (diversity_score × 0.25)
```

| Factor | Weight | Source Column | Description |
|--------|--------|---------------|-------------|
| `balance_score` | 50% | `net_balance` | Normalised net balance (0–100) |
| `activity_score` | 25% | `transaction_count` | Normalised transaction count (0–100) |
| `diversity_score` | 25% | `unique_categories` | Normalised unique categories used (0–100) |

**Normalisation** uses min-max scaling computed at query time across all users:

```python
score = ((value - min_value) / (max_value - min_value + epsilon)) * 100
```

`epsilon = 1e-9` prevents division by zero when all users have identical values.

### 8.3 SQL Implementation

```sql
WITH stats AS (
    SELECT
        u.user_id,
        u.username,
        us.net_balance,
        us.transaction_count,
        us.unique_categories,
        MIN(us.net_balance)        OVER () AS min_bal,
        MAX(us.net_balance)        OVER () AS max_bal,
        MIN(us.transaction_count)  OVER () AS min_txn,
        MAX(us.transaction_count)  OVER () AS max_txn,
        MIN(us.unique_categories)  OVER () AS min_cat,
        MAX(us.unique_categories)  OVER () AS max_cat
    FROM users u
    JOIN user_stats us ON u.user_id = us.user_id
),
scored AS (
    SELECT
        *,
        ROUND(
            0.50 * ((net_balance       - min_bal) / NULLIF(max_bal - min_bal, 0) * 100) +
            0.25 * ((transaction_count - min_txn) / NULLIF(max_txn - min_txn, 0) * 100) +
            0.25 * ((unique_categories - min_cat) / NULLIF(max_cat - min_cat, 0) * 100)
        , 2) AS composite_score
    FROM stats
)
SELECT *, RANK() OVER (ORDER BY composite_score DESC) AS rank
FROM scored
ORDER BY rank
LIMIT $1 OFFSET $2;
```

### 8.4 Tie-Breaking

When two users have identical composite scores, they are further sorted by `last_transaction_at DESC` (most recently active ranks higher), then by `user_id` (deterministic UUID sort) to guarantee a stable, reproducible order.

---

## 9. Abuse & Manipulation Prevention

### 9.1 Rate Limiting

A per-user rate limit of **20 transactions per minute** is enforced using an in-memory sliding-window counter backed by a Python `asyncio.Lock`-protected `dict`. Exceeding the limit returns `429 Too Many Requests` with a `Retry-After` header.

```python
# Pseudo-code — actual impl uses asyncio-safe sliding window
if await rate_limiter.is_limited(user_id, limit=20, window_seconds=60):
    raise HTTPException(429, detail={"code": "RATE_LIMITED", "retry_after": 60})
```

For production, this would be backed by Redis; the in-memory version is documented as a simplification (see Section 12).

### 9.2 Amount Caps

Single transaction ceiling of **1,000,000** prevents a single large credit from dominating the balance-score factor completely.

### 9.3 Ranking Normalisation Prevents Stuffing

Because `activity_score` uses min-max normalisation, a user who sends 10,000 micro-transactions does not achieve a proportionally higher score than a user with 100 meaningful ones — they only shift the upper bound of the normalised range, which compresses everyone else's scores equally. The `balance_score` (50% weight) is unaffected by transaction volume.

### 9.4 Category Diversity Cap

`unique_categories` is capped at the total number of allowed categories (11). Sending the same category 1,000 times does not inflate the diversity factor beyond what one transaction of that category already contributed.

### 9.5 Negative Balance Floor

Debits that would reduce `net_balance` below **−50,000** are rejected. This prevents a user from using large negative balances to game any future inverse-ranking features and also catches erroneous inputs.

### 9.6 Input Sanitisation

All string inputs are stripped, lowercased where appropriate, and matched against strict allowlists or regex patterns before reaching the database. No raw user input is interpolated into SQL — all queries use parameterised statements via asyncpg.

---

## 10. Error Handling

### 10.1 Error Response Shape

Every error response follows a consistent envelope:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable description",
    "details": [
      { "field": "amount", "issue": "Must be greater than 0" }
    ]
  }
}
```

### 10.2 HTTP Status Code Map

| Status | When used |
|--------|-----------|
| 200 | Duplicate idempotency replay |
| 201 | New transaction created |
| 400 | Malformed request / validation failure |
| 402 | Debit would breach balance floor |
| 404 | User not found |
| 422 | Semantically invalid input (e.g., bad category) |
| 429 | Rate limit exceeded |
| 500 | Unhandled server/database error |

### 10.3 Global Exception Handler

A FastAPI `exception_handler` catches any unhandled `Exception`, logs the full traceback to stderr, and returns a `500` with `INTERNAL_ERROR` — never leaking stack traces to the client.

```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR",
        "message": "An unexpected error occurred"}})
```

### 10.4 Database Error Handling

`asyncpg.UniqueViolationError` on the idempotency key is caught explicitly and routed to the duplicate-replay path rather than surfacing as a 500.

Connection pool exhaustion raises a timeout after 10 s and returns a `503 SERVICE_UNAVAILABLE` with a `Retry-After: 5` header.

---

## 11. Frontend Requirements

### 11.1 Pages / Views

| View | Description |
|------|-------------|
| **Home / Dashboard** | Shows the global ranking table with pagination |
| **Submit Transaction** | Form to post a new transaction; shows success/duplicate/error feedback |
| **User Summary** | Enter a User ID to view that user's full financial summary and category breakdown |

### 11.2 Functional Requirements

- The ranking table auto-refreshes every 30 seconds.
- The transaction form pre-generates a UUID `idempotency_key` on page load, with a "Regenerate" button for retry flows.
- Duplicate responses are displayed with a distinct `⚠️ Already processed` banner rather than an error state.
- All API errors display the `error.code` and `error.message` from the response body.
- The category breakdown in the user summary is rendered as a simple bar chart (CSS-only or Chart.js).
- The score breakdown (`balance_score`, `activity_score`, `diversity_score`) is shown in a tooltip on the ranking table.
- The frontend enforces the same amount/category constraints client-side before submitting.

### 11.3 Non-Functional Requirements

- No authentication required — this is a demo system.
- The frontend communicates with the backend via the deployed API URL, configurable via an `.env` file (`VITE_API_BASE_URL`).
- The UI is responsive down to 375 px (mobile-first).

---

## 12. Assumptions & Mock Data

### 12.1 Documented Assumptions

| # | Assumption | Rationale |
|---|-----------|-----------|
| A1 | Users are pre-seeded; no `POST /user` endpoint is built | The assignment does not ask for user registration. Five mock users are seeded in the migration. |
| A2 | Rate limiting uses in-memory storage | A Redis dependency would add significant setup overhead. In production this would be replaced with Redis. |
| A3 | Balance floor is **−50,000** | An arbitrary but documented business rule to prevent unbounded debits. |
| A4 | Idempotency keys expire after **24 hours** | The `transactions` table can be periodically cleaned of old keys if needed. For this assignment, expiry is not actively enforced — all keys are retained indefinitely. |
| A5 | `unique_categories` in `user_stats` is updated by re-counting distinct categories on each transaction write | Simpler than maintaining a separate `user_categories` join table for this scope. |
| A6 | Composite score weights (50/25/25) are hard-coded | Suitable for this assignment; in a real system these would be configurable. |
| A7 | No authentication or JWT | Out of scope per assignment requirements. |

### 12.2 Seed Data

Five mock users are inserted by the database migration:

| username | user_id (UUID) |
|----------|---------------|
| alice | `aaa00000-0000-0000-0000-000000000001` |
| bob | `bbb00000-0000-0000-0000-000000000002` |
| carol | `ccc00000-0000-0000-0000-000000000003` |
| dave | `ddd00000-0000-0000-0000-000000000004` |
| eve | `eee00000-0000-0000-0000-000000000005` |

A seed script (`scripts/seed.py`) inserts ~50 diverse transactions across these users to demonstrate a populated ranking and meaningful summaries from first launch.

---

## 13. Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app init, middleware, CORS
│   │   ├── config.py             # Settings (pydantic-settings, .env)
│   │   ├── database.py           # asyncpg pool setup
│   │   ├── routers/
│   │   │   ├── transaction.py    # POST /transaction
│   │   │   ├── summary.py        # GET /summary/:userId
│   │   │   └── ranking.py        # GET /ranking
│   │   ├── services/
│   │   │   ├── transaction_service.py   # Business logic, idempotency, lock
│   │   │   ├── summary_service.py       # Summary aggregation
│   │   │   └── ranking_service.py       # Composite score computation
│   │   ├── models/
│   │   │   ├── requests.py       # Pydantic request models
│   │   │   └── responses.py      # Pydantic response models
│   │   ├── middleware/
│   │   │   └── rate_limiter.py   # Sliding-window rate limiter
│   │   └── exceptions.py         # Custom exception classes + handlers
│   ├── migrations/
│   │   └── 001_initial_schema.sql
│   ├── scripts/
│   │   └── seed.py               # Seed mock users and transactions
│   ├── tests/
│   │   ├── test_transaction.py
│   │   ├── test_ranking.py
│   │   └── test_summary.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx     # Ranking table
│   │   │   ├── Submit.jsx        # Transaction form
│   │   │   └── Summary.jsx       # User summary view
│   │   ├── components/
│   │   │   ├── RankingTable.jsx
│   │   │   ├── TransactionForm.jsx
│   │   │   ├── CategoryChart.jsx
│   │   │   └── ScoreTooltip.jsx
│   │   └── api/
│   │       └── client.js         # Axios instance with base URL + error handling
│   ├── .env.example
│   ├── package.json
│   └── vite.config.js
├── docker-compose.yml            # Backend + PostgreSQL for local dev
└── README.md
```

---

## 14. Setup & Running

### 14.1 Local Development

```bash
# 1. Clone and enter the repo
git clone <repo-url> && cd <repo>

# 2. Start PostgreSQL via Docker Compose
docker-compose up -d db

# 3. Install backend dependencies
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env: set DATABASE_URL=postgresql://postgres:password@localhost:5432/txndb

# 5. Run migrations and seed
psql $DATABASE_URL -f migrations/001_initial_schema.sql
python scripts/seed.py

# 6. Start the backend
uvicorn app.main:app --reload --port 8000

# 7. Start the frontend (separate terminal)
cd ../frontend
npm install
cp .env.example .env
# Edit .env: VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

### 14.2 Key Dependencies (`requirements.txt`)

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
asyncpg==0.29.0
pydantic==2.7.1
pydantic-settings==2.2.1
python-dotenv==1.0.1
httpx==0.27.0      # for tests
pytest==8.2.0
pytest-asyncio==0.23.6
```

### 14.3 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | Full asyncpg-compatible PostgreSQL DSN |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS origins (default: `*` for dev) |
| `RATE_LIMIT_PER_MINUTE` | No | Transactions per user per minute (default: `20`) |
| `BALANCE_FLOOR` | No | Minimum net balance allowed (default: `-50000`) |
| `MAX_TRANSACTION_AMOUNT` | No | Per-transaction ceiling (default: `1000000`) |

---

*End of Requirements Document*
