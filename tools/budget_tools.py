"""
tools/budget_tools.py

Security hardening applied:
  [CRIT-4] All budget amounts and categories validated before DB writes.
"""

from typing import List, Dict
from langchain_core.tools import tool
from database.manager import upsert_budget, get_budgets, get_monthly_summary, get_category_monthly_spend
from security.validators import validate_budget_amount, validate_category, ValidationError


@tool
def manage_budgets(user_id: int, budget_configs: List[Dict]):
    """
    Sets or updates multiple budgets at once.
    - user_id: The ID of the user.
    - budget_configs: A list of dicts like [{"category": "Food", "amount": 500}, {"category": "Total", "amount": 2000}]
    Use 'Total' for the overall monthly budget.
    """
    results = []
    for config in budget_configs:
        cat = config.get("category", "")
        amt = config.get("amount")

        # Validate — allow "Total" as a special category name without Title-casing it
        try:
            if cat != "Total":
                cat = validate_category(cat)
            amt = validate_budget_amount(amt)
        except ValidationError as exc:
            results.append(f"Skipped '{cat}': {exc}")
            continue

        upsert_budget(user_id, cat, amt)
        results.append(f"{cat}: Rs{amt:,.0f}")

    if not results:
        return "No budgets were updated."
    return "Successfully updated budgets:\n" + "\n".join(results)


@tool
def get_budget_report(user_id: int):
    """
    Generates a report of current spending vs budgets.
    """
    budgets = get_budgets(user_id)
    if not budgets:
        return "You haven't set any budgets yet. Use 'manage_budgets' to get started!"

    summary     = get_monthly_summary(user_id)
    total_spent = summary.get("expense", 0.0)

    report = ["Monthly Budget Report"]

    for cat, limit in budgets.items():
        current = total_spent if cat == "Total" else get_category_monthly_spend(user_id, cat)
        percent = (current / limit * 100) if limit > 0 else 0
        status  = "OK" if percent < 80 else "WARNING" if percent < 100 else "EXCEEDED"

        report.append(f"{status} {cat}: Rs{current:,.0f} / Rs{limit:,.0f} ({percent:.1f}%)")
        bar_len = 10
        filled  = min(int(percent / 10), bar_len)
        bar     = "=" * filled + "-" * (bar_len - filled)
        report.append(f"   [{bar}]")

    return "\n".join(report)
