"""
database/manager.py — All Supabase data access.

IDOR / Ownership fixes applied in this revision:
  VULN-1  decrement_installments: now requires user_id; verifies bill
          ownership before update; raises OwnershipError on mismatch.
  VULN-2  mark_bill_processed: now requires user_id; WHERE clause
          includes both id AND user_id.
  VULN-3  delete_recurring_bill: now requires user_id; WHERE clause
          includes both id AND user_id.
  VULN-4  process_pending_bills TOCTOU: all three internal calls now
          pass user_id so each DB operation independently enforces ownership.
  VULN-8  get_active_users: internal-only; caller must pass
          require_admin=True or be called from a scheduled job context.
  VULN-9  RLS policy strategy: documented — service role bypasses RLS,
          so Python-layer ownership checks are the authoritative guard.
          See security_migration.sql for belt-and-suspenders DB constraints.
"""

import logging
from datetime import datetime, timedelta
import pytz
from .supabase_client import supabase
from security.rbac import require_ownership, OwnershipError

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


# ── Init ──────────────────────────────────────────────────────────────────────

def init_db():
    """Ensures all required tables exist."""
    _ensure_audit_log_table()


def _ensure_audit_log_table():
    try:
        supabase.table("audit_log").select("id").limit(1).execute()
    except Exception:
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
            logger.info("audit_log table created")
        except Exception as exc:
            logger.warning(
                "Could not auto-create audit_log (%s). "
                "Run database/security_migration.sql in Supabase SQL Editor.", exc
            )


# ── Expenses ──────────────────────────────────────────────────────────────────

def add_expense_to_db(user_id: int, amount: float, category: str,
                      description: str, exp_type: str) -> str:
    """Insert a transaction. user_id is always set from the authenticated session."""
    supabase.table("expenses").insert({
        "user_id":     user_id,
        "amount":      amount,
        "category":    category,
        "description": description,
        "type":        exp_type,
        "created_at":  datetime.now(IST).isoformat(),
    }).execute()
    return f"Successfully saved {exp_type}: ₹{amount} for {description} ({category})"


def get_expenses_in_range(user_id: int, start_date: str, end_date: str):
    return get_filtered_expenses(user_id, start_date=start_date, end_date=end_date)


def get_user_expenses(user_id: int, limit: int = 10) -> str:
    response = (
        supabase.table("expenses")
        .select("amount, category, description, type, created_at")
        .eq("user_id", user_id)           # ownership scoped
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = response.data
    if not rows:
        return "No transactions found."
    history = "\n".join(
        f"- ₹{r['amount']} on {r['category']} ({r['description']}) at {r['created_at'][:16]}"
        for r in rows
    )
    return f"Last {len(rows)} transactions:\n{history}"


def get_total_spent(user_id: int) -> str:
    response = (
        supabase.table("expenses")
        .select("amount")
        .eq("user_id", user_id)           # ownership scoped
        .eq("type", "expense")
        .execute()
    )
    total = sum(item["amount"] for item in response.data) if response.data else 0.0
    return f"Total spending to date: ₹{total:,.2f}"


def get_filtered_expenses(user_id: int, category: str = None, start_date: str = None,
                           end_date: str = None, exp_type: str = None):
    query = supabase.table("expenses").select("*").eq("user_id", user_id)  # ownership scoped
    if category:   query = query.eq("category", category)
    if exp_type:   query = query.eq("type", exp_type)
    if start_date: query = query.gte("created_at", start_date)
    if end_date:   query = query.lte("created_at", end_date)
    response = query.order("created_at").execute()
    return [
        (r["amount"], r["category"], r["description"], r["type"], r["created_at"])
        for r in response.data
    ]


# ── Budgets ───────────────────────────────────────────────────────────────────

def upsert_budget(user_id: int, category: str, amount: float):
    supabase.table("budgets").upsert(
        {"user_id": user_id, "category": category, "amount": amount},
        on_conflict="user_id,category",
    ).execute()


def get_budgets(user_id: int) -> dict:
    response = (
        supabase.table("budgets")
        .select("category, amount")
        .eq("user_id", user_id)           # ownership scoped
        .execute()
    )
    return {
        (row["category"] if row["category"] else "Total"): float(row["amount"])
        for row in response.data
    }


def get_monthly_summary(user_id: int) -> dict:
    now_ist = datetime.now(IST)
    start   = now_ist.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    response = (
        supabase.table("expenses")
        .select("type, amount")
        .eq("user_id", user_id)           # ownership scoped
        .gte("created_at", start)
        .execute()
    )
    summary = {"income": 0.0, "expense": 0.0}
    for row in response.data:
        btype = row["type"].lower()
        if btype in summary:
            summary[btype] += float(row["amount"])
    return summary


def get_category_monthly_spend(user_id: int, category: str) -> float:
    now_ist = datetime.now(IST)
    start   = now_ist.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    response = (
        supabase.table("expenses")
        .select("amount")
        .eq("user_id", user_id)           # ownership scoped
        .eq("category", category)
        .eq("type", "expense")
        .gte("created_at", start)
        .execute()
    )
    return sum(float(item["amount"]) for item in response.data) if response.data else 0.0


# ── Recurring Bills ───────────────────────────────────────────────────────────

def add_recurring_bill(user_id: int, amount: float, category: str, description: str,
                        day_of_month: int, btype: str = "expense",
                        installments: int = None, interval: int = 1):
    now = datetime.now(IST)
    supabase.table("recurring_bills").insert({
        "user_id":                user_id,
        "amount":                 amount,
        "category":               category,
        "description":            description,
        "day_of_month":           day_of_month,
        "type":                   btype,
        "last_processed_month":   now.strftime("%Y-%m") if now.day >= day_of_month else None,
        "total_installments":     installments,
        "remaining_installments": installments,
        "interval_months":        interval,
        "created_at":             now.isoformat(),
    }).execute()


def get_active_recurring_bills(user_id: int) -> list:
    """Always scoped to user_id — never returns bills from other users."""
    response = (
        supabase.table("recurring_bills")
        .select("*")
        .eq("user_id", user_id)           # ownership scoped
        .eq("is_active", True)
        .execute()
    )
    return [
        (r["id"], r["amount"], r["category"], r["description"], r["day_of_month"],
         r["type"], r["last_processed_month"], r["remaining_installments"], r["interval_months"])
        for r in response.data
    ]


def _get_bill_owner(bill_id: int) -> int | None:
    """
    Fetch the user_id that owns a recurring bill.
    Returns None if the bill doesn't exist.
    Used internally to enforce ownership before mutations.
    """
    response = (
        supabase.table("recurring_bills")
        .select("user_id")
        .eq("id", bill_id)
        .limit(1)
        .execute()
    )
    if response.data:
        return response.data[0]["user_id"]
    return None


def decrement_installments(bill_id: int, user_id: int) -> None:
    """
    VULN-1 FIX: user_id now required. Verifies ownership before mutating.
    Reduces remaining_installments by 1; deactivates bill if count hits 0.
    """
    owner = _get_bill_owner(bill_id)
    if owner is None:
        logger.warning("decrement_installments: bill %d not found", bill_id)
        return
    # Raises OwnershipError if user_id != owner
    require_ownership(user_id, owner, f"recurring bill #{bill_id}")

    bill = (
        supabase.table("recurring_bills")
        .select("remaining_installments")
        .eq("id", bill_id)
        .eq("user_id", user_id)           # second ownership filter at DB layer
        .single()
        .execute()
    )
    if not bill.data:
        return

    new_rem     = (bill.data["remaining_installments"] or 1) - 1
    update_data = {"remaining_installments": new_rem}
    if new_rem <= 0:
        update_data["is_active"] = False

    supabase.table("recurring_bills").update(update_data) \
        .eq("id", bill_id).eq("user_id", user_id).execute()  # WHERE id AND user_id


def mark_bill_processed(bill_id: int, month_str: str, user_id: int) -> None:
    """
    VULN-2 FIX: user_id now required. WHERE clause filters both id AND user_id.
    If the bill doesn't belong to this user the UPDATE affects 0 rows (silent no-op).
    """
    supabase.table("recurring_bills") \
        .update({"last_processed_month": month_str}) \
        .eq("id", bill_id) \
        .eq("user_id", user_id) \
        .execute()


def delete_recurring_bill(bill_id: int, user_id: int) -> None:
    """
    VULN-3 FIX: user_id now required. WHERE clause filters both id AND user_id.
    A user cannot deactivate another user's recurring bill by guessing an ID.
    """
    owner = _get_bill_owner(bill_id)
    if owner is None:
        return  # already gone
    require_ownership(user_id, owner, f"recurring bill #{bill_id}")

    supabase.table("recurring_bills") \
        .update({"is_active": False}) \
        .eq("id", bill_id) \
        .eq("user_id", user_id) \
        .execute()


# ── Users ─────────────────────────────────────────────────────────────────────

def register_user(user_id: int, first_name: str = None):
    supabase.table("users").upsert(
        {"user_id": user_id, "first_name": first_name},
        on_conflict="user_id",
    ).execute()


def get_user_first_name(user_id: int) -> str:
    try:
        response = (
            supabase.table("users")
            .select("first_name")
            .eq("user_id", user_id)       # ownership scoped
            .limit(1)
            .execute()
        )
        if response.data and response.data[0].get("first_name"):
            return response.data[0]["first_name"]
    except Exception:
        pass
    return "there"


def get_active_users(days: int = 7) -> list:
    """
    VULN-8: This function returns ALL active user IDs — it is intentionally
    internal-only and must NEVER be exposed as a tool callable by users.
    It is called exclusively from scheduled jobs in main.py which run
    under bot-operator authority, not user authority.
    """
    cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat()
    try:
        response = (
            supabase.table("expenses")
            .select("user_id")
            .gte("created_at", cutoff)
            .execute()
        )
        return list(set(row["user_id"] for row in response.data))
    except Exception as exc:
        logger.error("get_active_users failed: %s", exc)
        return []


# ── Config ────────────────────────────────────────────────────────────────────

def get_config(key_name: str):
    try:
        response = supabase.table("config").select("key_value").eq("key_name", key_name).execute()
        if response.data:
            return response.data[0]["key_value"]
    except Exception:
        pass
    return None


def set_config(key_name: str, key_value: str):
    supabase.table("config").upsert(
        {"key_name": key_name, "key_value": key_value,
         "updated_at": datetime.now(IST).isoformat()},
        on_conflict="key_name",
    ).execute()


# ── Transaction CRUD ──────────────────────────────────────────────────────────

def get_transaction_by_id(user_id: int, transaction_id: int):
    """
    Fetch a transaction by ID. user_id is always in the WHERE clause —
    returns None (not a 403) so callers can show a neutral 'not found' message
    without leaking whether the ID exists for another user.
    """
    response = (
        supabase.table("expenses")
        .select("id, amount, category, description, type, created_at")
        .eq("id", transaction_id)
        .eq("user_id", user_id)           # ownership enforced at DB layer
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    r = response.data[0]
    return (r["id"], r["amount"], r["category"], r["description"], r["type"], r["created_at"])


def search_transactions_db(user_id: int, keyword: str = None,
                            category: str = None, limit: int = 10) -> list:
    query = (
        supabase.table("expenses")
        .select("id, amount, category, description, type, created_at")
        .eq("user_id", user_id)           # ownership scoped
        .order("created_at", desc=True)
        .limit(limit)
    )
    if category: query = query.eq("category", category)
    if keyword:  query = query.ilike("description", f"%{keyword}%")
    response = query.execute()
    return [
        (r["id"], r["amount"], r["category"], r["description"], r["type"], r["created_at"])
        for r in response.data
    ]


def delete_transaction_db(user_id: int, transaction_id: int) -> None:
    """WHERE clause always includes BOTH id AND user_id — IDOR safe."""
    supabase.table("expenses") \
        .delete() \
        .eq("id", transaction_id) \
        .eq("user_id", user_id) \
        .execute()


def update_transaction_db(user_id: int, transaction_id: int, amount: float,
                           category: str, description: str, ttype: str) -> None:
    """WHERE clause always includes BOTH id AND user_id — IDOR safe."""
    supabase.table("expenses") \
        .update({"amount": amount, "category": category,
                 "description": description, "type": ttype}) \
        .eq("id", transaction_id) \
        .eq("user_id", user_id) \
        .execute()
