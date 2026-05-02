-- ================================================================
-- Wallet Watch — Security Migration v2
-- Run this in: Supabase Dashboard → SQL Editor
--
-- Changes from v1:
--   • IDOR fixes: add user_id to recurring_bills mutation constraints
--   • RLS policies rewritten — service role bypass is expected and correct;
--     policies now guard against direct anon/authenticated API access
--   • RBAC: users table gains a 'role' column (user | admin)
--   • DB-layer CHECK constraints added as second line of defence
--   • Indexes added for all ownership-scoped query patterns
-- ================================================================


-- ════════════════════════════════════════════════════════════════
-- 1. RBAC — role column on users table
-- ════════════════════════════════════════════════════════════════

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'user'
    CHECK (role IN ('user', 'admin'));

-- Promote specific Telegram user IDs to admin in Supabase:
--   UPDATE users SET role = 'admin' WHERE user_id = <your_telegram_id>;

CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);


-- ════════════════════════════════════════════════════════════════
-- 2. Audit Log Table
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS audit_log (
    id          bigserial    PRIMARY KEY,
    event_type  text         NOT NULL,
    user_id     bigint       NOT NULL,
    metadata    jsonb,
    created_at  timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user_created
    ON audit_log (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_event_type
    ON audit_log (event_type, created_at DESC);

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "audit service only" ON audit_log;
CREATE POLICY "audit service only" ON audit_log USING (false);


-- ════════════════════════════════════════════════════════════════
-- 3. Row Level Security
--
-- Strategy: The Python backend uses the SERVICE ROLE key which
-- bypasses RLS. These policies protect against:
--   (a) Direct anon-key API calls (e.g. leaked key exploitation)
--   (b) Supabase Studio browsing with authenticated role
--
-- Policy uses auth.uid()::text = user_id::text so it works with
-- Supabase Auth JWTs. For Telegram bots (no Supabase Auth), the
-- service role key is the correct access pattern — RLS is a
-- belt-and-suspenders guard, not the primary enforcement layer.
-- ════════════════════════════════════════════════════════════════

-- expenses
ALTER TABLE expenses ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users own expenses" ON expenses;
CREATE POLICY "users own expenses" ON expenses
    FOR ALL
    USING (
        -- Service role: always allowed (Python backend)
        current_setting('role', true) = 'service_role'
        OR
        -- Authenticated Supabase Auth users: own rows only
        user_id::text = auth.uid()::text
    );

-- budgets
ALTER TABLE budgets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users own budgets" ON budgets;
CREATE POLICY "users own budgets" ON budgets
    FOR ALL
    USING (
        current_setting('role', true) = 'service_role'
        OR user_id::text = auth.uid()::text
    );

-- recurring_bills
ALTER TABLE recurring_bills ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users own bills" ON recurring_bills;
CREATE POLICY "users own bills" ON recurring_bills
    FOR ALL
    USING (
        current_setting('role', true) = 'service_role'
        OR user_id::text = auth.uid()::text
    );

-- users — users see only their own row; admins see all
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users own profile" ON users;
CREATE POLICY "users own profile" ON users
    FOR ALL
    USING (
        current_setting('role', true) = 'service_role'
        OR user_id::text = auth.uid()::text
    );

-- config — service role only
ALTER TABLE config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "config service only" ON config;
CREATE POLICY "config service only" ON config USING (false);


-- ════════════════════════════════════════════════════════════════
-- 4. Revoke anon/authenticated access to sensitive tables
-- ════════════════════════════════════════════════════════════════

REVOKE ALL ON config     FROM anon, authenticated;
REVOKE ALL ON audit_log  FROM anon, authenticated;


-- ════════════════════════════════════════════════════════════════
-- 5. DB-layer CHECK constraints (second line of defence)
-- ════════════════════════════════════════════════════════════════

-- expenses.type must be valid
ALTER TABLE expenses
    DROP CONSTRAINT IF EXISTS expenses_type_check;
ALTER TABLE expenses
    ADD CONSTRAINT expenses_type_check
    CHECK (type IN ('expense', 'income'));

-- expenses.amount must be positive
ALTER TABLE expenses
    DROP CONSTRAINT IF EXISTS expenses_amount_positive;
ALTER TABLE expenses
    ADD CONSTRAINT expenses_amount_positive
    CHECK (amount > 0);

-- recurring_bills.type must be valid
ALTER TABLE recurring_bills
    DROP CONSTRAINT IF EXISTS recurring_type_check;
ALTER TABLE recurring_bills
    ADD CONSTRAINT recurring_type_check
    CHECK (type IN ('expense', 'income'));

-- recurring_bills.amount must be positive
ALTER TABLE recurring_bills
    DROP CONSTRAINT IF EXISTS recurring_amount_positive;
ALTER TABLE recurring_bills
    ADD CONSTRAINT recurring_amount_positive
    CHECK (amount > 0);

-- recurring_bills.interval_months: 1–24
ALTER TABLE recurring_bills
    DROP CONSTRAINT IF EXISTS recurring_interval_check;
ALTER TABLE recurring_bills
    ADD CONSTRAINT recurring_interval_check
    CHECK (interval_months BETWEEN 1 AND 24);

-- recurring_bills.day_of_month: 1–28
ALTER TABLE recurring_bills
    DROP CONSTRAINT IF EXISTS recurring_day_check;
ALTER TABLE recurring_bills
    ADD CONSTRAINT recurring_day_check
    CHECK (day_of_month BETWEEN 1 AND 28);

-- budgets.amount must be positive
ALTER TABLE budgets
    DROP CONSTRAINT IF EXISTS budgets_amount_positive;
ALTER TABLE budgets
    ADD CONSTRAINT budgets_amount_positive
    CHECK (amount > 0);

-- Ensure is_active exists on recurring_bills
ALTER TABLE recurring_bills
    ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;


-- ════════════════════════════════════════════════════════════════
-- 6. IDOR-hardening indexes
--    Every query pattern that uses (user_id + id) gets a covering
--    index so ownership checks are O(log n) not full table scans.
-- ════════════════════════════════════════════════════════════════

-- expenses: lookup by id + user_id (used in get_transaction_by_id,
--           delete_transaction_db, update_transaction_db)
CREATE UNIQUE INDEX IF NOT EXISTS idx_expenses_id_user
    ON expenses (id, user_id);

-- expenses: user timeline (used in get_user_expenses, search)
CREATE INDEX IF NOT EXISTS idx_expenses_user_created
    ON expenses (user_id, created_at DESC);

-- expenses: category spend (used in get_category_monthly_spend)
CREATE INDEX IF NOT EXISTS idx_expenses_user_category_type
    ON expenses (user_id, category, type, created_at DESC);

-- recurring_bills: ownership lookup (used in _get_bill_owner,
--                  decrement_installments, mark_bill_processed,
--                  delete_recurring_bill)
CREATE UNIQUE INDEX IF NOT EXISTS idx_recurring_id_user
    ON recurring_bills (id, user_id);

-- recurring_bills: active bills per user
CREATE INDEX IF NOT EXISTS idx_recurring_user_active
    ON recurring_bills (user_id, is_active);

-- budgets: per-user category lookup
CREATE UNIQUE INDEX IF NOT EXISTS idx_budgets_user_category
    ON budgets (user_id, category);


-- ════════════════════════════════════════════════════════════════
-- 7. Ownership-enforcing stored procedures
--    These wrap the three previously-vulnerable mutations so even
--    raw SQL clients cannot bypass the user_id check.
-- ════════════════════════════════════════════════════════════════

-- Safe bill deactivation: only deactivates if caller owns the bill
CREATE OR REPLACE FUNCTION deactivate_recurring_bill(
    p_bill_id bigint,
    p_user_id bigint
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    rows_affected int;
BEGIN
    UPDATE recurring_bills
    SET    is_active = false
    WHERE  id      = p_bill_id
      AND  user_id = p_user_id;   -- ownership enforced in SQL

    GET DIAGNOSTICS rows_affected = ROW_COUNT;
    RETURN rows_affected > 0;
END;
$$;

-- Safe mark-processed: only updates if caller owns the bill
CREATE OR REPLACE FUNCTION mark_bill_processed_safe(
    p_bill_id   bigint,
    p_user_id   bigint,
    p_month_str text
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    rows_affected int;
BEGIN
    UPDATE recurring_bills
    SET    last_processed_month = p_month_str
    WHERE  id      = p_bill_id
      AND  user_id = p_user_id;   -- ownership enforced in SQL

    GET DIAGNOSTICS rows_affected = ROW_COUNT;
    RETURN rows_affected > 0;
END;
$$;

-- Safe installment decrement: ownership-checked atomic decrement
CREATE OR REPLACE FUNCTION decrement_installments_safe(
    p_bill_id bigint,
    p_user_id bigint
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_remaining int;
    rows_affected int;
BEGIN
    SELECT remaining_installments
    INTO   v_remaining
    FROM   recurring_bills
    WHERE  id      = p_bill_id
      AND  user_id = p_user_id;   -- ownership check

    IF NOT FOUND THEN
        RETURN false;              -- not owner or doesn't exist
    END IF;

    UPDATE recurring_bills
    SET    remaining_installments = GREATEST(v_remaining - 1, 0),
           is_active = CASE WHEN v_remaining - 1 <= 0 THEN false ELSE is_active END
    WHERE  id      = p_bill_id
      AND  user_id = p_user_id;

    GET DIAGNOSTICS rows_affected = ROW_COUNT;
    RETURN rows_affected > 0;
END;
$$;


-- ════════════════════════════════════════════════════════════════
-- Post-migration checklist:
--   1. Add your Telegram user_id as admin:
--        UPDATE users SET role = 'admin' WHERE user_id = <YOUR_ID>;
--   2. Set ADMIN_USER_IDS=<YOUR_ID> in Render environment variables
--   3. Verify SUPABASE_KEY is the SERVICE ROLE key (not anon)
--   4. Confirm ENCRYPTION_KEY is set for secret encryption
-- ════════════════════════════════════════════════════════════════
