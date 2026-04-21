from langchain_core.tools import tool
from database.manager import add_expense_to_db, get_user_expenses, get_total_spent

@tool
def log_transaction(user_id: int, amount: float, category: str, description: str, type: str):
    """
    Saves a financial transaction (expense or income) to the database.
    - user_id: The unique ID of the user.
    - amount: The numeric value of the transaction.
    - category: e.g., Food, Transport, Salary, Utilities.
    - description: A short note about the transaction.
    - type: Must be 'expense' or 'income'.
    """
    return add_expense_to_db(user_id, amount, category, description, type)

@tool
def check_history(user_id: int):
    """Fetches the recent transaction history for the user."""
    return get_user_expenses(user_id)

@tool
def get_spending_summary(user_id: int):
    """Calculates the total amount spent by the user across all time."""
    return get_total_spent(user_id)
