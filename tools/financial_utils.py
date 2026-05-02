"""
tools/financial_utils.py

Security hardening applied:
  [CRIT-4] All tool arguments validated via security/validators.py before
           any database call.  Negative amounts, oversized strings, and
           invalid type values are rejected with a clear user-facing error.
"""

from langchain_core.tools import tool
from database.manager import (
    add_expense_to_db,
    get_user_expenses,
    get_total_spent,
    get_budgets,
    get_category_monthly_spend,
    get_monthly_summary,
)
from security.validators import (
    validate_amount,
    validate_type,
    validate_category,
    validate_description,
    ValidationError,
)


@tool
def log_transaction(user_id: int, amount: float, category: str, description: str, type: str):
    """
    Saves a financial transaction (expense or income) to the database.
    - user_id: The unique ID of the user (injected from system context).
    - amount: The numeric value of the transaction (must be > 0).
    - category: e.g., Food, Transport, Salary, Utilities.
    - description: A short note about the transaction.
    - type: Must be exactly 'expense' or 'income'.
    """
    # [CRIT-4] Validate every argument before touching the database
    try:
        amount      = validate_amount(amount)
        ttype       = validate_type(type)
        category    = validate_category(category)
        description = validate_description(description)
    except ValidationError as exc:
        return f"❌ Invalid input: {exc}"

    result = add_expense_to_db(user_id, amount, category, description, ttype)

    if ttype == "expense":
        alerts = []

        # Category budget check
        budgets = get_budgets(user_id)
        if category in budgets:
            limit   = budgets[category]
            current = get_category_monthly_spend(user_id, category)
            percent = (current / limit * 100) if limit > 0 else 0
            if percent >= 100:
                alerts.append(
                    f"🚨 BUDGET EXCEEDED: You've spent ₹{current:,.0f} on {category} "
                    f"(limit: ₹{limit:,.0f})!"
                )
            elif percent >= 80:
                alerts.append(
                    f"⚠️ BUDGET WARNING: {percent:.1f}% of your {category} budget used."
                )

        # Total budget check
        if "Total" in budgets:
            limit        = budgets["Total"]
            monthly_data = get_monthly_summary(user_id)
            total_exp    = monthly_data.get("expense", 0.0)
            percent      = (total_exp / limit * 100) if limit > 0 else 0
            if percent >= 100:
                alerts.append(
                    f"🚨 TOTAL BUDGET EXCEEDED: ₹{total_exp:,.0f} spent "
                    f"(limit: ₹{limit:,.0f})!"
                )
            elif percent >= 80:
                alerts.append(
                    f"⚠️ TOTAL BUDGET: {percent:.1f}% of your monthly budget used."
                )

        # Negative cash-flow warning
        monthly_data = get_monthly_summary(user_id)
        total_income = monthly_data.get("income", 0.0)
        total_exp    = monthly_data.get("expense", 0.0)
        if total_exp > total_income > 0:
            alerts.append(
                f"🚩 NEGATIVE CASH FLOW: Monthly spend ₹{total_exp:,.0f} "
                f"exceeds income ₹{total_income:,.0f}."
            )

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
