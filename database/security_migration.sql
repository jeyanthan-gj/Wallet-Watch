-- ============================================================
-- Wallet Watch — Security Migration
-- Run this in Supabase SQL Editor (Settings > SQL Editor)
-- ============================================================

-- ── 1. Audit Log Table ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id          bigserial    PRIMARY KEY,
    event_type  text         NOT NULL,
    user_id     bigint       NOT NULL,
    metadata    jsonb,
    created_at  timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user_created
    ON audit_log (user_id, created_at DESC);

-- Only the service role (your backend) can touch this table.
-- No anon/authenticated client can read or write audit rows.
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service only" ON audit_log;
CREATE POLICY "service only" ON audit_log USING (false);


-- ── 2. Row Level Security on all user-data tables ───────────
-- These policies ensure that even if the anon key leaks,
-- users cannot read each other's data through the Supabase API.
-- Your backend uses the SERVICE ROLE key which bypasses RLS.

-- expenses
ALTER TABLE expenses ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users see own expenses" ON expenses;
CREATE POLICY "users see own expenses" ON expenses
    USING (user_id = current_setting('app.current_user_id')::bigint);

-- budgets
ALTER TABLE budgets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users see own budgets" ON budgets;
CREATE POLICY "users see own budgets" ON budgets
    USING (user_id = current_setting('app.current_user_id')::bigint);

-- recurring_bills
ALTER TABLE recurring_bills ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users see own bills" ON recurring_bills;
CREATE POLICY "users see own bills" ON recurring_bills
    USING (user_id = current_setting('app.current_user_id')::bigint);

-- users
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users see own profile" ON users;
CREATE POLICY "users see own profile" ON users
    USING (user_id = current_setting('app.current_user_id')::bigint);

-- config — service role only (API keys etc.)
ALTER TABLE config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service only config" ON config;
CREATE POLICY "service only config" ON config USING (false);


-- ── 3. Revoke anon key access to sensitive tables ───────────
-- Belt-and-suspenders: even with RLS enabled, revoke direct grants.
REVOKE ALL ON config     FROM anon, authenticated;
REVOKE ALL ON audit_log  FROM anon, authenticated;


-- ── 4. Constrain expenses.type to valid values ──────────────
-- Enforces [CRIT-4] at the DB layer as a second line of defence.
ALTER TABLE expenses
    DROP CONSTRAINT IF EXISTS expenses_type_check;
ALTER TABLE expenses
    ADD CONSTRAINT expenses_type_check
    CHECK (type IN ('expense', 'income'));


-- ── 5. Add amount > 0 constraint ────────────────────────────
ALTER TABLE expenses
    DROP CONSTRAINT IF EXISTS expenses_amount_positive;
ALTER TABLE expenses
    ADD CONSTRAINT expenses_amount_positive
    CHECK (amount > 0);


-- ── 6. Soft-delete support for recurring_bills ──────────────
-- already has is_active column per existing schema; confirm it exists
ALTER TABLE recurring_bills
    ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;


-- ── 7. Index for rate-limit queries (if you move to DB-backed rate limiting) ──
CREATE INDEX IF NOT EXISTS idx_expenses_user_created
    ON expenses (user_id, created_at DESC);


-- ============================================================
-- After running this migration:
-- 1. Rotate your TELEGRAM_BOT_TOKEN via @BotFather
--    (the old token from .env.example is now public)
-- 2. Rotate your GEMINI_API_KEY in Google AI Studio
-- 3. Generate a Fernet ENCRYPTION_KEY and add it to Render env vars:
--      python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
-- 4. Ensure SUPABASE_KEY is the SERVICE ROLE key, not the anon key
-- ============================================================
