# Transaction & Ranking Service

A financial-transaction backend with a per-user summary API and a multi-factor
leaderboard, paired with a Next.js dashboard. Built to be **safe under
concurrent load**, **idempotent by construction**, and **resistant to ranking
manipulation**.

> Implements every requirement from [`REQUIREMENTS.md`](./REQUIREMENTS.md)
> (§1–§14). Frontend uses **Next.js** instead of the spec's React+Vite stack.

---

## Table of Contents

1. [What was built (requirements traceability)](#1-what-was-built-requirements-traceability)
2. [Tech stack & why each piece was chosen](#2-tech-stack--why-each-piece-was-chosen)
3. [Architecture](#3-architecture)
4. [Database design](#4-database-design)
5. [API reference](#5-api-reference)
6. [Concurrency, idempotency & consistency](#6-concurrency-idempotency--consistency)
7. [Ranking logic](#7-ranking-logic)
8. [Abuse & manipulation prevention](#8-abuse--manipulation-prevention)
9. [Optimisation techniques used (and why)](#9-optimisation-techniques-used-and-why)
10. [Frontend design](#10-frontend-design)
11. [Project structure](#11-project-structure)
12. [Setup & running](#12-setup--running)
13. [Testing](#13-testing)
14. [Environment variables](#14-environment-variables)
15. [Assumptions & trade-offs](#15-assumptions--trade-offs)

---

## 1. What was built (requirements traceability)

Every section of `REQUIREMENTS.md` is implemented:

| Spec § | Requirement | Where |
|--------|-------------|-------|
| §3 | Schema: `users`, `transactions`, `user_stats` + indexes | `backend/migrations/001_initial_schema.sql` |
| §4.1 | `POST /transaction` (201 new / 200 duplicate) | `app/routers/transaction.py`, `app/services/transaction_service.py` |
| §4.2 | `GET /summary/:userId` with live `category_breakdown` | `app/routers/summary.py`, `app/services/summary_service.py` |
| §4.3 | `GET /ranking` with pagination + composite score | `app/routers/ranking.py`, `app/services/ranking_service.py` |
| §5.1 | Pydantic field validators (key length, amount precision, enum, category allow-list) | `app/models/__init__.py` |
| §5.2 | Cross-field: `−50,000` balance floor → `402 INSUFFICIENT_FUNDS` | `transaction_service.py` |
| §6.2 | `SELECT … FOR UPDATE` row lock on `user_stats` | `transaction_service.py` |
| §6.3 | asyncpg pool (min 5 / max 20 / 10s timeout) | `app/database.py`, `app/config.py` |
| §7 | Idempotency via `UNIQUE` + `ON CONFLICT DO NOTHING … RETURNING` | `transaction_service.py` |
| §8 | Composite score `0.5·balance + 0.25·activity + 0.25·diversity`, min-max, tie-break | `ranking_service.py` |
| §9.1 | Per-user sliding-window rate limit (20/min) → `429` + `Retry-After` | `app/middleware/rate_limiter.py` |
| §9.2–9.6 | Amount cap, normalisation, category cap, balance floor, sanitisation | models + services |
| §10 | Unified `{error:{code,message,details}}` envelope + global handler | `app/exceptions.py` |
| §11 | Dashboard / Submit / Summary pages, 30s refresh, duplicate banner, score tooltip, CSS bar chart, client-side validation | `frontend/src/` |
| §12.2 | 5 seeded users + ~50 diverse transactions | `scripts/seed.py` + migration |
| §13 | Project layout | see §11 below |
| §14 | Setup, Dockerfile, docker-compose, env vars | root + `backend/` + `frontend/` |

---

## 2. Tech stack & why each piece was chosen

| Layer | Technology | Why this and not the alternatives |
|-------|-----------|-----------------------------------|
| **Backend framework** | **FastAPI 0.115** | Async-native (one event loop serves thousands of idle connections); automatic OpenAPI/Swagger at `/docs`; Pydantic v2 validation runs before any DB call. Chosen over Flask (sync) and Django (heavier, ORM hides the SQL we need to hand-tune). |
| **DB driver** | **asyncpg 0.30** | Non-blocking Postgres driver; supports server-side prepared statements, `RETURNING`, and pipeline protocol. Much faster than psycopg2 in an async context. |
| **Database** | **PostgreSQL 16** | ACID + `SELECT FOR UPDATE` row locks + transaction-level advisory locks + `UNIQUE` constraints. We rely on all three for correctness — SQLite/MySQL lack the locking guarantees we need. |
| **Validation / settings** | **Pydantic 2.10 + pydantic-settings** | Declarative, fast (Rust core), auto-generates the JSON schema for `/docs`. |
| **Decimal math** | Python `Decimal` + Postgres `NUMERIC(18,2)` | Eliminates floating-point drift on money. A `FLOAT` column would silently corrupt balances. |
| **ASGI server** | **uvicorn** | Standard FastAPI server; `--reload` for dev, multi-worker in prod. |
| **Frontend framework** | **Next.js 14 (App Router)** | See §10. The spec suggested React+Vite; Next.js was requested instead and gives us SSR/RSC, file-based routing, image/font optimisation, and zero-config API env handling. |
| **HTTP client (FE)** | Native `fetch` | Next.js polyfills it server-side; avoids an axios bundle for a 3-endpoint app. |
| **Tests** | **pytest + pytest-asyncio + httpx** | Test the ASGI app end-to-end through httpx's `ASGITransport` with dependency overrides — no running server needed. |

---

## 3. Architecture

```
┌──────────────┐   HTTPS (JSON)    ┌──────────────────────────────┐
│  Next.js FE  │ ───────────────▶  │   FastAPI Backend             │
│  (port 3000) │                   │  ┌─────────┐ ┌──────────┐    │
│              │ ◀───────────────  │  │ Routers │ │ Services │    │
└──────────────┘                   │  └─────────┘ └──────────┘    │
                                   │        │                       │
                                   │  ┌─────▼──────────┐           │
                                   │  │ asyncpg Pool    │           │
                                   │  │ TTL cache       │           │
                                   │  │ Rate limiter    │           │
                                   │  └────────────────┘           │
                                   └──────────────┬───────────────┘
                                                  │
                                          ┌───────▼───────┐
                                          │ PostgreSQL 16 │
                                          └───────────────┘
```

**Request flow for `POST /transaction`** (the critical path):

```
client → Pydantic validation (400 on bad shape)
       → rate limiter (429 if over 20/min)
       → BEGIN
       →   SELECT … FOR UPDATE on user_stats        ← serialises per-user writes
       →   INSERT … ON CONFLICT DO NOTHING RETURNING ← exactly-once
       →       0 rows? → fetch original, return 200 is_duplicate=true
       →       1 row?  → UPDATE user_stats atomically
       →                  (debit?) check balance floor → 402 + rollback if breached
       → COMMIT
       → invalidate ranking cache
       → return 201
```

---

## 4. Database design

Three tables (`backend/migrations/001_initial_schema.sql`):

- **`users`** — seeded identities (§3.1).
- **`transactions`** — append-only ledger. `idempotency_key UNIQUE` is the
  exactly-once guarantee; `(user_id, created_at DESC)` and
  `(user_id, category)` indexes make summary/breakdown queries cheap (§3.2).
- **`user_stats`** — **materialised aggregates** maintained inside the same
  transaction as every write, so `/summary` headlines and `/ranking` inputs are
  O(1) reads instead of full-table `SUM`s (§3.3).

The migration is **idempotent** (`CREATE … IF NOT EXISTS`, `ON CONFLICT DO
NOTHING`) and runs automatically on app startup unless `AUTO_MIGRATE=0`.

---

## 5. API reference

Interactive docs at **`http://localhost:8000/docs`** once running.

### `POST /transaction` → `201` (new) | `200` (duplicate)

```jsonc
// request
{
  "idempotency_key": "txn-abc-1234",      // 8–128 chars, [a-zA-Z0-9-]
  "user_id": "aaa00000-0000-0000-0000-000000000001",
  "type": "credit",                       // "credit" | "debit"
  "amount": 250.00,                       // > 0, ≤ 1,000,000, ≤ 2 dp
  "category": "salary",                   // from allow-list
  "description": "Monthly salary"         // optional, ≤ 255 chars
}
// response adds: transaction_id, status, created_at, is_duplicate
```

Errors: `400 VALIDATION_ERROR`, `402 INSUFFICIENT_FUNDS`, `404 USER_NOT_FOUND`,
`422 INVALID_CATEGORY`, `429 RATE_LIMITED`, `500 INTERNAL_ERROR`.

### `GET /summary/{user_id}` → `200`

Headline numbers from `user_stats` (O(1)) + `category_breakdown` computed live
from `transactions` (indexed). Errors: `400 INVALID_UUID`, `404 USER_NOT_FOUND`.

### `GET /ranking?page=1&limit=10` → `200`

Paginated board sorted by composite score. `limit` capped at 50.

### `GET /health` → `200 {"status":"ok"}`

Liveness probe used by docker-compose.

**Error envelope** (uniform across every failure path, §10.1):

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "...", "details": [...] } }
```

---

## 6. Concurrency, idempotency & consistency

### Race-free aggregation (`SELECT FOR UPDATE`)

Two concurrent credits for the same user would otherwise both read
`net_balance = 100`, both add `50`, both write `150` — a **lost update**. We
prevent this by locking the user's `user_stats` row for the duration of the
transaction (`app/services/transaction_service.py`). Different users are
unaffected, so cross-user throughput stays high.

### Exactly-once processing

The `idempotency_key UNIQUE` constraint plus `INSERT … ON CONFLICT DO NOTHING
RETURNING` means: if two identical requests race, Postgres guarantees exactly
one `INSERT` wins. The loser sees zero rows from `RETURNING`, takes the
duplicate path, and **skips the stats update entirely** — no double-credit.

### Balance floor enforced atomically

If a debit would push `net_balance < −50,000`, we raise `402` *inside* the
transaction. Raising aborts both the `INSERT` and the `UPDATE`, so the user
isn't charged and the idempotency key is freed for a corrected retry.

---

## 7. Ranking logic

The composite score prevents gaming by volume alone (§8):

```
composite_score = 0.50 × balance_score + 0.25 × activity_score + 0.25 × diversity_score
```

Each factor is **min-max normalised across all users at query time** with
`NULLIF` guarding division by zero. The entire pipeline — join, windowed
min/max, per-user score, deterministic ranking — runs in **one SQL statement**
via a CTE chain (`app/services/ranking_service.py`). No Python-side loops, no
N+1.

**Tie-break (§8.4):** `composite_score DESC, last_transaction_at DESC NULLS LAST,
user_id ASC` — fully deterministic and reproducible.

---

## 8. Abuse & manipulation prevention

| Control | Mechanism | Location |
|--------|-----------|----------|
| Rate limit | 20 req/user/min, true sliding window (not fixed window — bursts can't straddle a boundary) | `middleware/rate_limiter.py` |
| Amount cap | ≤ 1,000,000 per transaction | Pydantic `Field(le=1_000_000)` |
| Decimal precision | ≤ 2 dp (`as_tuple().exponent`) blocks `0.001` tricks | `models/__init__.py` |
| Diversity cap | `unique_categories` re-counted per write; max = 11 allowed categories | `transaction_service.py` |
| Balance floor | Debits below −50,000 rejected | `transaction_service.py` |
| Normalisation | Min-max scaling means spamming micro-txns only shifts the upper bound, compressing everyone equally; balance (50% weight) is volume-independent | `ranking_service.py` |
| Input sanitisation | `strip()` + `lower()` + allow-lists + parameterised queries (no string interpolation) | models + all SQL |

---

## 9. Optimisation techniques used (and why)

These go beyond the literal spec and are the techniques I added to make the
system faster and more robust. Each is explained so you can audit the trade-off.

### 9.1 Materialised aggregates (`user_stats`) — *spec-required*

Every write updates `user_stats` inside the same transaction. `/summary`
headlines and `/ranking` inputs are then O(1) row reads instead of full-table
`SUM`/`COUNT`. **Why:** aggregation at read time on a million-row ledger would
make `/ranking` take seconds; materialising makes it milliseconds.

### 9.2 Single-statement ranking SQL — *spec-required*

The whole leaderboard is one CTE pipeline (`stats → scored → numbered`). The
database does the join, windowed min/max, scoring and pagination in one
round-trip. **Why:** pulling rows into Python to score them would be O(N)
network + O(N log N) sort in the app — the DB does it in one pass with indexes.

### 9.3 In-process TTL cache for `/ranking` — *added*

`app/middleware/ttl_cache.py` memoises the serialised ranking response for
`RANKING_CACHE_TTL` seconds (default 15). Page-1 is polled by every client
every 30s; caching lets Postgres skip the window-function work on hits. Any
successful `POST /transaction` calls `clear()` so the board never shows stale
data for more than the cache window.

**Why not Redis?** Redis is the prod answer (and called out in §15), but adding
it for a demo inflates setup. **Why not `functools.lru_cache`?** It has no TTL,
so data would linger until restart. The hand-rolled version is monotonic-clock
based (immune to wall-clock changes) and `asyncio.Lock`-safe.

### 9.4 Connection pooling (asyncpg, min 5 / max 20) — *spec-required*

Connections are expensive to establish; the pool reuses them. `command_timeout=10s`
kills runaway queries; `max_inactive_connection_lifetime=300s` cycles stale
connections behind load balancers. **Why:** per-request `connect()`/`close()`
would add 20–50ms of TCP+TLS+auth overhead to every call.

### 9.5 Composite indexes tuned to the actual queries — *added beyond spec*

- `(user_id, created_at DESC)` — `/summary` ordering + recent-activity lookups.
- `(user_id, category)` — the live `category_breakdown` `GROUP BY`.
- `UNIQUE(idempotency_key)` — doubles as the dedup index used by `ON CONFLICT`.

**Why:** without `(user_id, category)` the breakdown query seq-scans all of a
user's rows on every summary request.

### 9.6 Sliding-window rate limiter (not fixed window) — *added robustness*

A fixed window lets a user fire 20 at `:59` and 20 more at `:00` = 40 in one
second. Our limiter stores timestamps and trims to the last 60s, so the quota
is exact regardless of boundary alignment. **Why:** correctness of the abuse
control matters more than the trivial extra bookkeeping.

### 9.7 Decimal end-to-end, never float — *correctness*

`Decimal` in Pydantic → `NUMERIC(18,2)` in Postgres → `Decimal` back out.
**Why:** `250.00 + 250.00` in float is fine, but `0.1 + 0.2` isn't, and over
millions of rows the drift becomes real money.

### 9.8 Idempotent, re-runnable migration & seed — *operability*

`CREATE … IF NOT EXISTS` + `ON CONFLICT DO NOTHING` mean `docker compose up`
works on a fresh volume **and** on a re-run without manual cleanup. The seed
script recomputes `user_stats` from scratch at the end, so it doubles as a
repair tool if aggregates ever drift.

### 9.9 Frontend: SSR-ready Next.js + `fetch(no-store) + setInterval` refresh

- App Router gives file-based routing and React Server Components, so the
  shell ships minimal JS (First Load JS ≈ 90 kB total — see the build output).
- The dashboard polls every 30s but uses `no-store` so Next's request cache
  never serves a stale board.
- **CSS-only bar chart & tooltip** (no Chart.js) — zero chart-library JS, instant
  paint, fully responsive down to 375px.

### 9.10 Fast failure before DB access — *latency*

Pydantic validation, rate-limiting, and UUID parsing all run before a
connection is acquired, so a malformed request never consumes a pooled
connection. This keeps the pool available for legitimate traffic.

---

## 10. Frontend design

Next.js 14 **App Router** (the spec asked for React+Vite; Next.js was requested
instead — Next.js *is* React, but adds routing, SSR/RSC, and build
optimisation out of the box).

| Route | File | Spec § |
|-------|------|--------|
| `/` Dashboard | `src/app/page.js` | §11.1 — ranking table, 30s auto-refresh, pagination |
| `/submit` | `src/app/submit/page.js` + `TransactionForm.js` | §11.1 — pre-generated idempotency key + Regenerate, client-side validation, distinct ⚠️ duplicate banner |
| `/summary` | `src/app/summary/page.js` + `CategoryChart.js` | §11.1 — UUID entry, stat cards, CSS bar chart |
| components | `RankingTable.js`, `ScoreTooltip.js` | §11.2 — score breakdown in a hover tooltip |

Key behaviours implemented (§11.2):
- Auto-refresh every 30s on the dashboard.
- UUID `idempotency_key` pre-generated on load, with a **Regenerate** button.
- Duplicate (HTTP 200) responses show a `⚠️ Already processed` banner, not an error.
- API errors render `error.code` + `error.message`.
- Category breakdown as a CSS bar chart; score breakdown in a tooltip.
- Same amount/category constraints enforced client-side before submit.
- Responsive down to 375px (mobile-first CSS).

API base URL is configurable via `NEXT_PUBLIC_API_BASE_URL` (§11.3).

---

## 11. Project structure

```
.
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, lifespan, CORS, handlers
│   │   ├── config.py               # pydantic-settings
│   │   ├── database.py             # asyncpg pool + get_conn dependency
│   │   ├── exceptions.py           # domain errors + envelope handlers
│   │   ├── routers/{transaction,summary,ranking}.py
│   │   ├── services/{transaction,summary,ranking}_service.py
│   │   ├── models/__init__.py      # Pydantic request/response models
│   │   └── middleware/{rate_limiter,ttl_cache}.py
│   ├── migrations/001_initial_schema.sql
│   ├── scripts/seed.py
│   ├── tests/{conftest,test_transaction,test_ranking,test_summary}.py
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/{layout,page}.js + submit/ + summary/
│   │   ├── components/{NavBar,RankingTable,TransactionForm,CategoryChart,ScoreTooltip}.js
│   │   ├── api/client.js
│   │   └── lib/{constants,format}.js
│   ├── next.config.mjs · jsconfig.json · package.json
│   ├── Dockerfile
│   └── .env.example
├── docker-compose.yml
├── REQUIREMENTS.md
└── README.md
```

---

## 12. Setup & running

### Option A — Docker Compose (whole stack, one command)

```bash
docker compose up --build
# backend  → http://localhost:8000  (docs at /docs)
# frontend → http://localhost:3000
# Postgres → localhost:5432
```

Compose runs the migration on startup, seeds ~50 transactions, and starts both
services.

### Option B — Local dev (no Docker)

```bash
# 1. Postgres (any way you like; e.g.):
docker run -d --name pg -e POSTGRES_PASSWORD=password -e POSTGRES_DB=txndb -p 5432:5432 postgres:16-alpine

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set DATABASE_URL if not default
python -m scripts.seed          # applies migration + seeds data
uvicorn app.main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
cp .env.example .env            # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev
```

---

## 13. Testing

```bash
cd backend
source .venv/bin/activate
python -m pytest                # 21 tests, no DB required
```

The suite uses httpx's `ASGITransport` against the ASGI app with a dependency
override for `get_conn`, so it exercises validation, rate-limiting, pagination,
the error envelope, and the composite-score formula without a live database.
Pure-scoring math is unit-tested directly against the documented normalisation.

```
21 passed in 0.55s
```

---

## 14. Environment variables

### Backend (`backend/.env`)

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DATABASE_URL` | yes | `postgresql://postgres:password@localhost:5432/txndb` | asyncpg DSN |
| `ALLOWED_ORIGINS` | no | `*` | comma-separated CORS origins |
| `RATE_LIMIT_PER_MINUTE` | no | `20` | per-user transaction limit |
| `BALANCE_FLOOR` | no | `-50000` | minimum net balance |
| `MAX_TRANSACTION_AMOUNT` | no | `1000000` | per-transaction ceiling |
| `RANKING_CACHE_TTL` | no | `15` | seconds to cache `/ranking` |
| `AUTO_MIGRATE` | no | `1` | run migration on startup |

### Frontend (`frontend/.env`)

| Variable | Required | Purpose |
|----------|----------|---------|
| `NEXT_PUBLIC_API_BASE_URL` | yes | backend URL, e.g. `http://localhost:8000` |

---

## 15. Assumptions & trade-offs

Carried over from REQUIREMENTS.md §12, with the additions flagged:

- **A1** Users pre-seeded (no `POST /user`). Five mock users ship in the migration.
- **A2** Rate limiting is in-memory (sliding window). **Production would use Redis**
  for multi-instance consistency — the `RateLimiter` interface is unchanged so the
  swap is a one-file change.
- **A3** Balance floor is `−50,000` (configurable via `BALANCE_FLOOR`).
- **A4** Idempotency keys retained indefinitely (no 24h sweep); expiry is a
  documented simplification.
- **A5** `unique_categories` recomputed per write via `COUNT(DISTINCT category)`.
- **A6** Score weights 50/25/25 hard-coded (would be configurable in prod).
- **A7** No auth/JWT — demo only.

**UUID note:** the spec's seed UUIDs (`aaa00000-…`) are valid UUIDs but not
strictly v4. The request model accepts any well-formed UUID (`uuid.UUID`) so
the documented seed data works; the path-param validator still rejects
non-UUIDs with `400 INVALID_UUID`.

**Version note:** `requirements.txt` pins to versions with Python 3.13 wheels
while preserving the documented stack. If you're on 3.11/3.12, the exact
versions from REQUIREMENTS.md §14.2 also work.

---

*Built per `REQUIREMENTS.md` — FastAPI · PostgreSQL · Next.js.*
