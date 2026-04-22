from datetime import datetime
from database.manager import get_active_recurring_bills, add_expense_to_db, mark_bill_processed, decrement_installments

def process_pending_bills(user_id: int):
    """
    Checks for any recurring bills that are due and logs them.
    Returns a list of confirmation messages.
    """
    now = datetime.now()
    current_month_str = now.strftime("%Y-%m")
    current_day = now.day
    
    active_bills = get_active_recurring_bills(user_id)
    notifications = []
    
    for bill in active_bills:
        bill_id, amount, category, description, day_of_month, btype, last_processed, remaining, interval = bill
        
        # Calculate month difference
        if last_processed:
            lp_y, lp_m = map(int, last_processed.split('-'))
            months_passed = (now.year - lp_y) * 12 + (now.month - lp_m)
        else:
            months_passed = interval # Treat new bills as due if day matches
            
        # Trigger if:
        # 1. Monthly day has arrived (or passed)
        # 2. Enough months have passed (months_passed >= interval)
        if current_day >= day_of_month and months_passed >= interval:
            # Log the transaction
            add_expense_to_db(user_id, amount, category, f"[RECURRING] {description}", btype)
            # Mark as processed
            mark_bill_processed(bill_id, current_month_str)
            
            # 📉 Handle EMI/Limited Duration
            if remaining is not None:
                decrement_installments(bill_id)
                rem_after = remaining - 1
                status = f" ({rem_after} remaining)" if rem_after > 0 else " (Final payment! ✅)"
            else:
                status = ""

            notifications.append(f"🔄 *Automated Log*: Your {btype} of ${amount} for '{description}' ({category}) has been recorded{status}.")
            
    return notifications
