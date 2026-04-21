from langchain_core.tools import tool
from database.manager import add_recurring_bill, get_active_recurring_bills, delete_recurring_bill

@tool
def setup_recurring_bill(user_id: int, amount: float, category: str, description: str, day_of_month: int, type: str = 'expense'):
    """
    Sets up a new recurring monthly transaction (e.g., Netflix, Rent, Salary).
    - user_id: The ID of the user.
    - amount: The numeric value.
    - category: e.g., Entertainment, Housing.
    - description: e.g., Netflix Subscription.
    - day_of_month: The day (1-31) when it should be logged every month.
    - type: 'expense' or 'income'.
    """
    if not (1 <= day_of_month <= 31):
        return "Error: day_of_month must be between 1 and 31."
        
    add_recurring_bill(user_id, amount, category, description, day_of_month, type)
    return f"Successfully setup recurring {type}: ${amount} for '{description}' on day {day_of_month} of every month."

@tool
def list_recurring_bills(user_id: int):
    """
    Returns a list of all active recurring transactions.
    """
    bills = get_active_recurring_bills(user_id)
    if not bills:
        return "No active recurring transactions found."
        
    lines = ["📝 *Active Recurring Transactions:*"]
    for b in bills:
        # id, amount, category, description, day_of_month, type, last_processed, remaining
        remaining_str = f" | {b[7]} left" if b[7] is not None else ""
        lines.append(f"- ID: `{b[0]}` | ${b[1]} {b[5]} for '{b[3]}' on day {b[4]}{remaining_str}")
        
    return "\n".join(lines)

@tool
def remove_recurring_bill(bill_id: int):
    """
    Deactivates a recurring transaction by its ID.
    """
    delete_recurring_bill(bill_id)
    return f"Recurring bill with ID {bill_id} has been deactivated."
