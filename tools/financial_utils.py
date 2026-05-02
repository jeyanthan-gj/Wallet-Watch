"""
tools/financial_utils.py — Core transaction and summary tools.
Uses shared parse_period / fmt_amount from tools/time_utils.py.
"""

from langchain_core.tools import tool
from database.manager import (
    add_expense_to_db, get_user_expenses, get_total_spent,
    get_budgets, get_category_monthly_spend, get_monthly_summary,
    get_filtered_expenses,
)
from security.validators import (
    validate_amount, validate_type, validate_category,
    validate_description, validate_limit, ValidationError,
)
from tools.time_utils import parse_period, fmt_amount


@tool
def log_transaction(user_id: int, amount: float, category: str, description: str, type: str):
    """
    Saves a financial transaction (expense or income) to the database.
    - user_id:      From system context — do not ask the user.
    - amount:       Numeric value, must be > 0.
    - category:     e.g. Food, Transport, Salary, Utilities, Entertainment.
    - description:  Short note e.g. 'Lunch at Saravana Bhavan'.
    - type:         Exactly 'expense' or 'income'.
    """
    try:
        amount      = validate_amount(amount)
        ttype       = validate_type(type)
        category    = validate_category(category)
        description = validate_description(description)
    except ValidationError as exc:
        return f"❌ Invalid input: {exc}"

    result = add_expense_to_db(user_id, amount, category, description, ttype)

    if ttype == "expense":
        alerts  = []
        budgets = get_budgets(user_id)

        if category in budgets:
            limit   = budgets[category]
            current = get_category_monthly_spend(user_id, category)
            percent = (current / limit * 100) if limit > 0 else 0
            if percent >= 100:
                alerts.append(f"🚨 BUDGET EXCEEDED: {fmt_amount(current)} spent on {category} (limit {fmt_amount(limit)})!")
            elif percent >= 80:
                alerts.append(f"⚠️ BUDGET WARNING: {percent:.1f}% of your {category} budget used.")

        if "Total" in budgets:
            limit     = budgets["Total"]
            monthly   = get_monthly_summary(user_id)
            total_exp = monthly.get("expense", 0.0)
            percent   = (total_exp / limit * 100) if limit > 0 else 0
            if percent >= 100:
                alerts.append(f"🚨 TOTAL BUDGET EXCEEDED: {fmt_amount(total_exp)} spent (limit {fmt_amount(limit)})!")
            elif percent >= 80:
                alerts.append(f"⚠️ TOTAL BUDGET: {percent:.1f}% of your monthly budget used.")

        monthly      = get_monthly_summary(user_id)
        total_income = monthly.get("income", 0.0)
        total_exp    = monthly.get("expense", 0.0)
        if total_exp > total_income > 0:
            alerts.append(
                f"🚩 NEGATIVE CASH FLOW: Spend {fmt_amount(total_exp)} exceeds "
                f"income {fmt_amount(total_income)} this month."
            )

        if alerts:
            result += "\n\n" + "\n".join(alerts)

    return result


@tool
def check_history(user_id: int, limit: int = 10):
    """
    Fetches recent transactions for the user.
    - limit: Number of transactions to return (default 10, max 50).
             If the user says 'show more' or 'last 20', pass the right number.
    """
    limit = validate_limit(limit, default=10, max_val=50)
    return get_user_expenses(user_id, limit=limit)


@tool
def get_spending_summary(user_id: int, period: str = "this month"):
    """
    Returns income, expenses and balance for a time period.
    - period: Any natural language period. Examples:
              'this month', 'last month', 'this year', 'last year',
              'today', 'last 7 days', 'last 3 months',
              'april', 'april 2026', 'march 2025'.
              Defaults to 'this month'.
    Use for ANY question about spending/income in a period.
    For all-time total, use period='all time'.
    """
    if period.lower().strip() in ("all time", "all", "total", "ever"):
        return get_total_spent(user_id)

    start, end = parse_period(period)
    rows       = get_filtered_expenses(user_id, start_date=start, end_date=end)

    income  = sum(float(r[0]) for r in rows if r[3] == "income")
    expense = sum(float(r[0]) for r in rows if r[3] == "expense")
    balance = income - expense
    label   = period.strip().title()

    if income == 0 and expense == 0:
        return f"No transactions found for {label}."

    lines = [f"📊 *Summary for {label}*"]
    lines.append(f"• 💰 Income:   {fmt_amount(income)}")
    lines.append(f"• 💸 Expenses: {fmt_amount(expense)}")
    if balance >= 0:
        lines.append(f"• ✅ Saved:    {fmt_amount(balance)}")
    else:
        lines.append(f"• 🚩 Deficit:  {fmt_amount(abs(balance))}")

    return "\n".join(lines)
