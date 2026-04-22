from langchain_core.tools import tool
from database.manager import (
    add_expense_to_db, 
    get_user_expenses, 
    get_total_spent, 
    get_budgets, 
    get_category_monthly_spend, 
    get_monthly_summary
)

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
    result = add_expense_to_db(user_id, amount, category, description, type)
    
    if type.lower() == "expense":
        # Check budgets and income
        alerts = []
        
        # 1. Check Category Budget
        budgets = get_budgets(user_id)
        if category in budgets:
            limit = budgets[category]
            current = get_category_monthly_spend(user_id, category)
            percent = (current / limit) * 100
            if percent >= 100:
                alerts.append(f"🚨 BUDGET EXCEEDED: You've spent ₹{current} on {category} (Limit: ₹{limit})!")
            elif percent >= 80:
                alerts.append(f"⚠️ BUDGET WARNING: You've used {percent:.1f}% of your {category} budget.")
        
        # 2. Check Total Budget
        if "Total" in budgets:
            limit = budgets["Total"]
            monthly_data = get_monthly_summary(user_id)
            current_total = monthly_data.get("expense", 0.0)
            percent = (current_total / limit) * 100
            if percent >= 100:
                alerts.append(f"🚨 TOTAL BUDGET EXCEEDED: Total spend ₹{current_total} (Limit: ₹{limit})!")
            elif percent >= 80:
                alerts.append(f"⚠️ TOTAL BUDGET WARNING: You've used {percent:.1f}% of your total monthly budget.")

        # 3. Check Income vs Expense
        monthly_data = get_monthly_summary(user_id)
        total_income = monthly_data.get("income", 0.0)
        total_expense = monthly_data.get("expense", 0.0)
        if total_expense > total_income > 0:
            alerts.append(f"🚩 NEGATIVE CASH FLOW: Your total monthly spending (₹{total_expense}) has exceeded your income (₹{total_income})!")

        if alerts:
            result += "\n\n" + "\n".join(alerts)
            
    return result

@tool
def check_history(user_id: int):
    """Fetches the recent transaction history for the user."""
    return get_user_expenses(user_id)

@tool
def get_spending_summary(user_id: int):
    """Calculates the total amount spent by the user across all time."""
    return get_total_spent(user_id)
