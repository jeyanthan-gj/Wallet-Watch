"""
tools/recurring_tools.py

IDOR fixes:
  - remove_recurring_bill now calls delete_recurring_bill(bill_id, user_id)
    which verifies ownership at the DB layer (not just via a Python set lookup).
  - All mutations pass user_id through to the DB functions.
"""

from langchain_core.tools import tool
from database.manager import (
    add_recurring_bill,
    get_active_recurring_bills,
    delete_recurring_bill,
)
from security.validators import (
    validate_amount, validate_category, validate_description,
    validate_day_of_month, validate_installments, validate_interval,
    validate_transaction_id, validate_type,
    ValidationError,
)
from security.audit_log import log_event
from security.rbac import OwnershipError


@tool
def setup_recurring_bill(
    user_id: int, amount: float, category: str, description: str,
    day_of_month: int, btype: str = "expense",
    installments: int = None, interval: int = 1,
):
    """
    Sets up a new recurring transaction (e.g., Netflix, Rent, EMI).
    - amount:       Numeric value, must be > 0.
    - category:     e.g., Entertainment, Housing.
    - description:  e.g., Netflix, Car EMI.
    - day_of_month: Day 1–28 when it logs each cycle.
    - btype:        'expense' or 'income'.
    - installments: Total payments (None = ongoing).
    - interval:     Months between payments (1 = monthly, 3 = quarterly).
    """
    try:
        amount       = validate_amount(amount)
        category     = validate_category(category)
        description  = validate_description(description)
        day_of_month = validate_day_of_month(day_of_month)
        btype        = validate_type(btype)
        installments = validate_installments(installments)
        interval     = validate_interval(interval)
    except ValidationError as exc:
        return f"❌ Invalid input: {exc}"

    add_recurring_bill(user_id, amount, category, description,
                       day_of_month, btype, installments, interval)

    interval_str = f"every {interval} months" if interval > 1 else "monthly"
    dur_str      = f"for {installments} payments" if installments else "ongoing"
    return (
        f"✅ Recurring {btype} set up: ₹{amount:,.0f} for '{description}' "
        f"on day {day_of_month}, {interval_str}, {dur_str}."
    )


@tool
def list_recurring_bills(user_id: int):
    """Returns a clean list of all active recurring transactions."""
    bills = get_active_recurring_bills(user_id)   # always scoped to user_id
    if not bills:
        return "You have no active recurring transactions."

    lines = ["📋 *Active Recurring Transactions:*\n"]
    for b in bills:
        bill_id, amount, category, description, day, btype, _, remaining, interval = b
        interval_str = f"every {interval} months" if interval > 1 else "monthly"
        dur_str      = f" | {remaining} left" if remaining is not None else " | ongoing"
        lines.append(
            f"#{bill_id} | ₹{amount:,.0f} {btype} | {description} "
            f"| day {day} {interval_str}{dur_str}"
        )
    return "\n".join(lines)


@tool
def remove_recurring_bill(user_id: int, bill_id: int):
    """
    Deactivates a recurring transaction by its ID.
    List bills first, then confirm with the user before calling this.
    - user_id: Verified against the bill owner at the DB layer.
    - bill_id: Shown in list_recurring_bills output.
    """
    try:
        bill_id = validate_transaction_id(bill_id)
    except ValidationError as exc:
        return f"❌ Invalid input: {exc}"

    try:
        log_event("recurring.remove", user_id, {"bill_id": bill_id})
        # IDOR FIX: delete_recurring_bill now takes user_id and verifies
        # ownership inside the DB function — no longer relies solely on
        # a Python-side set membership check.
        delete_recurring_bill(bill_id, user_id)
        return f"✅ Recurring bill #{bill_id} has been deactivated."
    except OwnershipError:
        return f"❌ Recurring bill #{bill_id} not found or does not belong to you."
