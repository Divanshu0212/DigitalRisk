-- 001_initial_schema.sql
-- Transaction & Ranking Service — initial schema.
-- Idempotent: safe to re-run (CREATE ... IF NOT EXISTS).
-- Applied automatically on app startup unless AUTO_MIGRATE=0.

-- Required for DEFAULT gen_random_uuid().
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      TEXT NOT NULL UNIQUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- transactions
-- Every accepted transaction lives here. idempotency_key UNIQUE enforces
-- exactly-once processing at the DB level (REQUIREMENTS §3.2, §7.2).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key  TEXT NOT NULL UNIQUE,
    user_id          UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    type             TEXT NOT NULL CHECK (type IN ('credit', 'debit')),
    amount           NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    category         TEXT NOT NULL,
    description      TEXT,
    status           TEXT NOT NULL DEFAULT 'success' CHECK (status IN ('success', 'failed')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Supports fast summary lookups + category-breakdown per user.
CREATE INDEX IF NOT EXISTS idx_transactions_user_created
    ON transactions(user_id, created_at DESC);

-- Redundant with the UNIQUE constraint on the column but explicit per spec.
CREATE INDEX IF NOT EXISTS idx_transactions_idempotency
    ON transactions(idempotency_key);

-- Composite index used by the live category_breakdown aggregation in /summary.
CREATE INDEX IF NOT EXISTS idx_transactions_user_category
    ON transactions(user_id, category);

-- ---------------------------------------------------------------------------
-- user_stats (materialised aggregates)
-- Updated atomically inside each transaction write (REQUIREMENTS §3.3).
-- Gives O(1) reads for /summary headline numbers and /ranking inputs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_stats (
    user_id              UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    total_credits        NUMERIC(18, 2) NOT NULL DEFAULT 0,
    total_debits         NUMERIC(18, 2) NOT NULL DEFAULT 0,
    net_balance          NUMERIC(18, 2) NOT NULL DEFAULT 0,
    transaction_count    INTEGER NOT NULL DEFAULT 0,
    unique_categories    INTEGER NOT NULL DEFAULT 0,
    last_transaction_at  TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Seed users (REQUIREMENTS §12.2). ON CONFLICT makes re-runs a no-op.
-- ---------------------------------------------------------------------------
INSERT INTO users (user_id, username) VALUES
    ('aaa00000-0000-0000-0000-000000000001', 'alice'),
    ('bbb00000-0000-0000-0000-000000000002', 'bob'),
    ('ccc00000-0000-0000-0000-000000000003', 'carol'),
    ('ddd00000-0000-0000-0000-000000000004', 'dave'),
    ('eee00000-0000-0000-0000-000000000005', 'eve')
ON CONFLICT (user_id) DO NOTHING;

-- Ensure every seeded user has a stats row so /transaction can lock it.
INSERT INTO user_stats (user_id)
SELECT user_id FROM users
ON CONFLICT (user_id) DO NOTHING;
