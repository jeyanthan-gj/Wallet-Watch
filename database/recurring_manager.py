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
        bill_id, amount, category, description, day_of_month, btype, last_processed, remaining = bill
        
        # If the day has arrived AND we haven't processed it this month
        if current_day >= day_of_month and last_processed != current_month_str:
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
