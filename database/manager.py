import os
import logging
from datetime import datetime, timedelta
import pytz
from .supabase_client import supabase

logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')


def init_db():
    """
    Ensures all required tables exist in Supabase.
    The audit_log table is created here if missing so the app
    works even before the SQL migration is run manually.
    """
    _ensure_audit_log_table()


def _ensure_audit_log_table():
    """Create audit_log table via RPC if it doesn't exist yet."""
    try:
        # Try a lightweight probe — if the table exists this succeeds instantly
        supabase.table("audit_log").select("id").limit(1).execute()
    except Exception:
        # Table missing — create it using raw SQL via Supabase RPC
        try:
            supabase.rpc("exec_sql", {"sql": """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id          bigserial    PRIMARY KEY,
                    event_type  text         NOT NULL,
                    user_id     bigint       NOT NULL,
                    metadata    jsonb,
                    created_at  timestamptz  NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_audit_log_user_created
                    ON audit_log (user_id, created_at DESC);
            """}).execute()
            logger.info("audit_log table created successfully")
        except Exception as exc:
            # RPC not available — log clearly so the operator knows to run the SQL migration
            logger.warning(
                "Could not auto-create audit_log table (%s). "
                "Please run database/security_migration.sql in Supabase SQL Editor.",
                exc
            )


def add_expense_to_db(user_id: int, amount: float, category: str, description: str, exp_type: str):
    """Saves a transaction to the Supabase database."""
    data = {
        "user_id": user_id,
        "amount": amount,
        "category": category,
        "description": description,
        "type": exp_type,
        "created_at": datetime.now(IST).isoformat()
    }
    supabase.table("expenses").insert(data).execute()
    return f"Successfully saved {exp_type}: ₹{amount} for {description} ({category})"


def get_expenses_in_range(user_id: int, start_date: str, end_date: str):
    """Alias for get_filtered_expenses specifically for date ranges."""
    return get_filtered_expenses(user_id, start_date=start_date, end_date=end_date)


def get_user_expenses(user_id: int, limit: int = 5):
    """Fetches the last N transactions for a specific user."""
    response = supabase.table("expenses") \
        .select("amount, category, description, type, created_at") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()

    rows = response.data
    if not rows:
        return "No transactions found."

    history = "\n".join([
        f"- ₹{r['amount']} on {r['category']} ({r['description']}) at {r['created_at'][:16]}"
        for r in rows
    ])
    return f"Last {len(rows)} transactions:\n{history}"


def get_total_spent(user_id: int):
    """Calculates total spend for a user across all categories and time."""
    response = supabase.table("expenses") \
        .select("amount") \
        .eq("user_id", user_id) \
        .eq("type", "expense") \
        .execute()

    total = sum(item['amount'] for item in response.data) if response.data else 0.0
    return f"Total spending to date: ₹{total:,.2f}"


def get_filtered_expenses(user_id: int, category: str = None, start_date: str = None,
                           end_date: str = None, exp_type: str = None):
    """Fetches expenses with optional filters."""
    query = supabase.table("expenses").select("*").eq("user_id", user_id)

    if category:   query = query.eq("category", category)
    if exp_type:   query = query.eq("type", exp_type)
    if start_date: query = query.gte("created_at", start_date)
    if end_date:   query = query.lte("created_at", end_date)

    response = query.order("created_at").execute()
    return [
        (r['amount'], r['category'], r['description'], r['type'], r['created_at'])
        for r in response.data
    ]


def upsert_budget(user_id: int, category: str, amount: float):
    """Sets or updates a budget for a category."""
    supabase.table("budgets").upsert(
        {"user_id": user_id, "category": category, "amount": amount},
        on_conflict="user_id,category"
    ).execute()


def get_budgets(user_id: int):
    """Retrieves all budgets for a user."""
    response = supabase.table("budgets").select("category, amount").eq("user_id", user_id).execute()
    return {
        (row['category'] if row['category'] else 'Total'): float(row['amount'])
        for row in response.data
    }


def get_monthly_summary(user_id: int):
    """Calculates total income and total expense for the current month in IST."""
    now_ist = datetime.now(IST)
    start_of_month = now_ist.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    response = supabase.table("expenses") \
        .select("type, amount") \
        .eq("user_id", user_id) \
        .gte("created_at", start_of_month) \
        .execute()

    summary = {"income": 0.0, "expense": 0.0}
    for row in response.data:
        btype = row['type'].lower()
        if btype in summary:
            summary[btype] += float(row['amount'])
    return summary


def get_category_monthly_spend(user_id: int, category: str):
    """Calculates total spend for a specific category in the current month in IST."""
    now_ist = datetime.now(IST)
    start_of_month = now_ist.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    response = supabase.table("expenses") \
        .select("amount") \
        .eq("user_id", user_id) \
        .eq("category", category) \
        .eq("type", "expense") \
        .gte("created_at", start_of_month) \
        .execute()

    return sum(float(item['amount']) for item in response.data) if response.data else 0.0


def add_recurring_bill(user_id: int, amount: float, category: str, description: str,
                        day_of_month: int, btype: str = 'expense',
                        installments: int = None, interval: int = 1):
    """Adds a new recurring transaction to Supabase with IST timestamp."""
    now = datetime.now(IST)
    last_processed = now.strftime("%Y-%m") if now.day >= day_of_month else None

    supabase.table("recurring_bills").insert({
        "user_id": user_id,
        "amount": amount,
        "category": category,
        "description": description,
        "day_of_month": day_of_month,
        "type": btype,
        "last_processed_month": last_processed,
        "total_installments": installments,
        "remaining_installments": installments,
        "interval_months": interval,
        "created_at": now.isoformat()
    }).execute()


def get_active_recurring_bills(user_id: int):
    """Fetches all active recurring bills for a user from Supabase."""
    response = supabase.table("recurring_bills") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .execute()

    return [
        (r['id'], r['amount'], r['category'], r['description'], r['day_of_month'],
         r['type'], r['last_processed_month'], r['remaining_installments'], r['interval_months'])
        for r in response.data
    ]


def decrement_installments(bill_id: int):
    """
    Reduces the remaining_installments count by 1 and deactivates the bill
    if the count reaches zero.

    FIX: Previously called RPC AND did client-side decrement — double-decrement bug.
    Now does only the client-side update (no RPC call).
    """
    bill = supabase.table("recurring_bills") \
        .select("remaining_installments") \
        .eq("id", bill_id) \
        .single() \
        .execute()

    if not bill.data:
        return

    new_rem = (bill.data['remaining_installments'] or 1) - 1
    update_data = {"remaining_installments": new_rem}
    if new_rem <= 0:
        update_data["is_active"] = False

    supabase.table("recurring_bills").update(update_data).eq("id", bill_id).execute()


def mark_bill_processed(bill_id: int, month_str: str):
    """Updates the last processed month for a recurring bill."""
    supabase.table("recurring_bills") \
        .update({"last_processed_month": month_str}) \
        .eq("id", bill_id) \
        .execute()


def delete_recurring_bill(bill_id: int):
    """Deactivates a recurring bill."""
    supabase.table("recurring_bills") \
        .update({"is_active": False}) \
        .eq("id", bill_id) \
        .execute()


def register_user(user_id: int, first_name: str = None):
    """Registers a new user or updates their name in Supabase."""
    supabase.table("users").upsert(
        {"user_id": user_id, "first_name": first_name},
        on_conflict="user_id"
    ).execute()


def get_user_first_name(user_id: int) -> str:
    """Fetches the stored first_name for a user, falls back to 'there'."""
    try:
        response = supabase.table("users") \
            .select("first_name") \
            .eq("user_id", user_id) \
            .limit(1) \
            .execute()
        if response.data and response.data[0].get("first_name"):
            return response.data[0]["first_name"]
    except Exception:
        pass
    return "there"


def get_active_users(days: int = 7):
    """
    Returns user_ids active in the last N days.
    Queries the users table directly so all registered users are included,
    not just those who have logged expenses.
    """
    cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat()

    try:
        # Primary: users who registered or had activity recently
        response = supabase.table("expenses") \
            .select("user_id") \
            .gte("created_at", cutoff) \
            .execute()
        return list(set(row['user_id'] for row in response.data))
    except Exception as exc:
        logger.error("get_active_users failed: %s", exc)
        return []


def get_config(key_name: str):
    """Fetches a configuration value from Supabase."""
    try:
        response = supabase.table("config").select("key_value").eq("key_name", key_name).execute()
        if response.data:
            return response.data[0]["key_value"]
    except Exception:
        pass
    return None


def set_config(key_name: str, key_value: str):
    """Updates or creates a configuration value in Supabase."""
    supabase.table("config").upsert(
        {"key_name": key_name, "key_value": key_value,
         "updated_at": datetime.now(IST).isoformat()},
        on_conflict="key_name"
    ).execute()


# ── Transaction CRUD ──────────────────────────────────────────────────────────

def get_transaction_by_id(user_id: int, transaction_id: int):
    """Fetches a single transaction by ID, verifying ownership."""
    response = supabase.table("expenses") \
        .select("id, amount, category, description, type, created_at") \
        .eq("id", transaction_id) \
        .eq("user_id", user_id) \
        .limit(1) \
        .execute()

    if not response.data:
        return None
    r = response.data[0]
    return (r["id"], r["amount"], r["category"], r["description"], r["type"], r["created_at"])


def search_transactions_db(user_id: int, keyword: str = None, category: str = None, limit: int = 10):
    """Searches transactions by keyword and/or category."""
    query = supabase.table("expenses") \
        .select("id, amount, category, description, type, created_at") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .limit(limit)

    if category: query = query.eq("category", category)
    if keyword:  query = query.ilike("description", f"%{keyword}%")

    response = query.execute()
    return [
        (r["id"], r["amount"], r["category"], r["description"], r["type"], r["created_at"])
        for r in response.data
    ]


def delete_transaction_db(user_id: int, transaction_id: int):
    """Hard-deletes a transaction, verifying ownership via user_id."""
    supabase.table("expenses") \
        .delete() \
        .eq("id", transaction_id) \
        .eq("user_id", user_id) \
        .execute()


def update_transaction_db(user_id: int, transaction_id: int, amount: float,
                           category: str, description: str, ttype: str):
    """Updates all editable fields of a transaction, verifying ownership."""
    supabase.table("expenses") \
        .update({"amount": amount, "category": category,
                 "description": description, "type": ttype}) \
        .eq("id", transaction_id) \
        .eq("user_id", user_id) \
        .execute()
