from langchain_core.tools import tool
from database.manager import add_recurring_bill, get_active_recurring_bills, delete_recurring_bill

@tool
def setup_recurring_bill(user_id: int, amount: float, category: str, description: str, day_of_month: int, btype: str = 'expense', installments: int = None, interval: int = 1):
    """
    Sets up a new recurring transaction (e.g., Netflix, Rent, EMI).
    - amount: The numeric value.
    - category: e.g., Entertainment, Housing.
    - description: e.g., Netflix, Car EMI.
    - day_of_month: The day (1-31) when it should be logged.
    - btype: 'expense' or 'income'.
    - installments: (Optional) Total number of times to log.
    - interval: (Optional) Months between payments (e.g. 2 for bi-monthly).
    """
    if not (1 <= day_of_month <= 31):
        return "Error: day_of_month must be between 1 and 31."
        
    add_recurring_bill(user_id, amount, category, description, day_of_month, btype, installments, interval)
    
    interval_str = f" every {interval} months" if interval > 1 else " monthly"
    dur_str = f" for {installments} times" if installments else " (ongoing)"
    return f"✅ Recurring {btype} set up: ₹{amount} for '{description}' on day {day_of_month}{interval_str}{dur_str}."

@tool
def list_recurring_bills(user_id: int):
    """
    Returns a clean list of all active recurring transactions.
    """
    bills = get_active_recurring_bills(user_id)
    if not bills:
        return "You have no active recurring transactions."
        
    lines = ["📋 *Active Recurring Transactions:*"]
    for b in bills:
        # id, amount, category, description, day_of_month, type, last_processed, remaining, interval
        amount, desc, day, btype, remaining, interval = b[1], b[3], b[4], b[5], b[7], b[8]
        
        interval_str = f"every {interval} months" if interval > 1 else "monthly"
        dur_str = f" | {remaining} installments left" if remaining is not None else " | ongoing"
        
        lines.append(f"• ₹{amount} {btype} for *{desc}* (on day {day} {interval_str}{dur_str})")
        
    return "\n".join(lines)

@tool
def remove_recurring_bill(bill_id: int):
    """
    Deactivates a recurring transaction by its ID.
    """
    delete_recurring_bill(bill_id)
    return f"Recurring bill with ID {bill_id} has been deactivated."
