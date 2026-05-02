"""
database/recurring_manager.py

VULN-4 FIX (TOCTOU):
  All three internal DB calls — add_expense_to_db, mark_bill_processed,
  decrement_installments — now pass user_id so each independently enforces
  ownership at the DB layer. A bill fetched for user A cannot be mutated
  for user B even if IDs are guessed or reused between calls.
"""

import logging
from datetime import datetime
import pytz

from database.manager import (
    get_active_recurring_bills,
    add_expense_to_db,
    mark_bill_processed,       # now requires user_id
    decrement_installments,    # now requires user_id
)
from security.rbac import OwnershipError

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def process_pending_bills(user_id: int) -> list:
    """
    Checks for recurring bills due for user_id and logs them.
    Returns a list of notification strings (may be empty).

    All DB mutations carry user_id so ownership is re-verified at each step.
    """
    now               = datetime.now(IST)
    current_month_str = now.strftime("%Y-%m")
    current_day       = now.day

    active_bills  = get_active_recurring_bills(user_id)   # always scoped to user_id
    notifications = []

    for bill in active_bills:
        bill_id, amount, category, description, day_of_month, btype, \
            last_processed, remaining, interval = bill

        # Calculate months since last processing
        if last_processed:
            try:
                lp_y, lp_m  = map(int, last_processed.split("-"))
                months_passed = (now.year - lp_y) * 12 + (now.month - lp_m)
            except (ValueError, AttributeError):
                months_passed = interval
        else:
            months_passed = interval

        if current_day >= day_of_month and months_passed >= interval:
            try:
                # 1. Log the transaction (user_id is authoritative here)
                add_expense_to_db(
                    user_id, amount, category, f"[RECURRING] {description}", btype
                )

                # VULN-4 FIX: pass user_id to every mutation
                # 2. Mark as processed — WHERE id AND user_id
                mark_bill_processed(bill_id, current_month_str, user_id)

                # 3. Decrement installments — verifies ownership before mutating
                if remaining is not None:
                    decrement_installments(bill_id, user_id)
                    rem_after = remaining - 1
                    status = (
                        f" ({rem_after} remaining)" if rem_after > 0
                        else " (Final payment! ✅)"
                    )
                else:
                    status = ""

                notifications.append(
                    f"🔄 *Automated Log*: ₹{amount} {btype} for '{description}' "
                    f"({category}) recorded{status}."
                )

            except OwnershipError as exc:
                # Should never happen in normal flow — log as security event
                logger.error(
                    "SECURITY: Ownership violation processing bill %d for user %d: %s",
                    bill_id, user_id, exc,
                )
            except Exception as exc:
                logger.error(
                    "Failed to process recurring bill %d for user %d: %s",
                    bill_id, user_id, exc,
                )

    return notifications
