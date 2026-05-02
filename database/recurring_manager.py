"""
database/recurring_manager.py

FIX: Use IST-aware datetime throughout — was using naive datetime.now()
     which could mis-fire bills near midnight IST.
"""

import logging
from datetime import datetime
import pytz

from database.manager import (
    get_active_recurring_bills, add_expense_to_db,
    mark_bill_processed, decrement_installments,
)

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def process_pending_bills(user_id: int):
    """
    Checks for any recurring bills that are due and logs them.
    Returns a list of notification strings (may be empty).
    """
    now = datetime.now(IST)          # FIX: was datetime.now() — naive, wrong timezone
    current_month_str = now.strftime("%Y-%m")
    current_day = now.day

    active_bills = get_active_recurring_bills(user_id)
    notifications = []

    for bill in active_bills:
        bill_id, amount, category, description, day_of_month, btype, \
            last_processed, remaining, interval = bill

        # Calculate months elapsed since last processing
        if last_processed:
            try:
                lp_y, lp_m = map(int, last_processed.split('-'))
                months_passed = (now.year - lp_y) * 12 + (now.month - lp_m)
            except (ValueError, AttributeError):
                months_passed = interval  # treat as due if unparseable
        else:
            months_passed = interval  # new bill, treat as due

        # Trigger only when both conditions are met:
        # 1. We are on or past the scheduled day of month
        # 2. Enough months have passed since last run
        if current_day >= day_of_month and months_passed >= interval:
            try:
                add_expense_to_db(user_id, amount, category, f"[RECURRING] {description}", btype)
                mark_bill_processed(bill_id, current_month_str)

                if remaining is not None:
                    decrement_installments(bill_id)
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
            except Exception as exc:
                logger.error(
                    "Failed to process recurring bill %d for user %d: %s",
                    bill_id, user_id, exc
                )

    return notifications
