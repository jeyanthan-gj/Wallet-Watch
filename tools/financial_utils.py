"""
tools/financial_utils.py

Fixes applied:
  [5] check_history now accepts a limit parameter (default 10, max 50)
  [7] get_monthly_summary tool added — returns income + expense for any period
      so "how much did I spend this month/last month?" works correctly
"""

from langchain_core.tools import tool
from database.manager import (
    add_expense_to_db,
    get_user_expenses,
    get_total_spent,
    get_budgets,
    get_category_monthly_spend,
    get_monthly_summary,
    get_filtered_expenses,
)
from security.validators import (
    validate_amount,
    validate_type,
    validate_category,
    validate_description,
    validate_limit,
    ValidationError,
)
import calendar
import re
import pytz
from datetime import datetime, timedelta

IST = pytz.timezone("Asia/Kolkata")

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _period_range(period: str):
    """Returns (start, end) YYYY-MM-DD for a period string."""
    now = datetime.now(IST)
    p = period.lower().strip()

    if "last month" in p:
        first_this = now.replace(day=1)
        last_end   = first_this - timedelta(days=1)
        last_start = last_end.replace(day=1)
        return last_start.strftime("%Y-%m-%d"), first_this.strftime("%Y-%m-%d")

    if "this month" in p or "current month" in p:
        return now.replace(day=1).strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    if "this year" in p:
        return now.replace(month=1, day=1).strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    if "last year" in p:
        s = now.replace(year=now.year-1, month=1, day=1)
        e = now.replace(month=1, day=1)
        return s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")

    if "today" in p:
        s = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return s.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # last N days/weeks/months
    m = re.search(r"last\s+(\d+)\s+(day|days|week|weeks|month|months)", p)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if "month" in unit:
            year, month = now.year, now.month - n
            while month <= 0:
                month += 12; year -= 1
            s = now.replace(year=year, month=month, day=1)
        elif "week" in unit:
            s = now - timedelta(weeks=n)
        else:
            s = now - timedelta(days=n)
        return s.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # named month: "april", "april 2026"
    for mname, mnum in _MONTHS.items():
        if re.search(rf"\b{mname}\b", p):
            yr_m = re.search(r"\b(20\d{2})\b", p)
            yr = int(yr_m.group(1)) if yr_m else now.year
            if yr == now.year and mnum > now.month:
                yr -= 1
            start = f"{yr}-{mnum:02d}-01"
            end = f"{yr}-{mnum+1:02d}-01" if mnum < 12 else f"{yr+1}-01-01"
            return start, end

    # default: this month
    return now.replace(day=1).strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")


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
        alerts = []
        budgets = get_budgets(user_id)

        if category in budgets:
            limit   = budgets[category]
            current = get_category_monthly_spend(user_id, category)
            percent = (current / limit * 100) if limit > 0 else 0
            if percent >= 100:
                alerts.append(f"🚨 BUDGET EXCEEDED: ₹{current:,.0f} spent on {category} (limit ₹{limit:,.0f})!")
            elif percent >= 80:
                alerts.append(f"⚠️ BUDGET WARNING: {percent:.1f}% of your {category} budget used.")

        if "Total" in budgets:
            limit     = budgets["Total"]
            monthly   = get_monthly_summary(user_id)
            total_exp = monthly.get("expense", 0.0)
            percent   = (total_exp / limit * 100) if limit > 0 else 0
            if percent >= 100:
                alerts.append(f"🚨 TOTAL BUDGET EXCEEDED: ₹{total_exp:,.0f} spent (limit ₹{limit:,.0f})!")
            elif percent >= 80:
                alerts.append(f"⚠️ TOTAL BUDGET: {percent:.1f}% of your monthly budget used.")

        monthly      = get_monthly_summary(user_id)
        total_income = monthly.get("income", 0.0)
        total_exp    = monthly.get("expense", 0.0)
        if total_exp > total_income > 0:
            alerts.append(f"🚩 NEGATIVE CASH FLOW: Spend ₹{total_exp:,.0f} exceeds income ₹{total_income:,.0f} this month.")

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
              Defaults to 'this month' if not specified.
    Use this whenever the user asks 'how much did I spend?', 'what's my balance?',
    'how much did I earn this month?', or any period-based summary question.
    For all-time total, use period='all time'.
    """
    if period.lower().strip() in ("all time", "all", "total", "ever"):
        return get_total_spent(user_id)

    start, end = _period_range(period)
    rows = get_filtered_expenses(user_id, start_date=start, end_date=end)

    income  = sum(float(r[0]) for r in rows if r[3] == "income")
    expense = sum(float(r[0]) for r in rows if r[3] == "expense")
    balance = income - expense

    # build a nice period label
    p = period.strip().title()

    lines = [f"📊 *Summary for {p}*"]
    lines.append(f"• 💰 Income:  ₹{income:,.2f}")
    lines.append(f"• 💸 Expenses: ₹{expense:,.2f}")
    if income > 0 or expense > 0:
        if balance >= 0:
            lines.append(f"• ✅ Saved:    ₹{balance:,.2f}")
        else:
            lines.append(f"• 🚩 Deficit:  ₹{abs(balance):,.2f}")

    if income == 0 and expense == 0:
        return f"No transactions found for {p}."

    return "\n".join(lines)
