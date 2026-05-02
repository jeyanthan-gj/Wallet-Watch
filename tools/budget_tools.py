"""
tools/budget_tools.py

Fixes applied:
  [6] get_budget_report: restored ₹ symbol and ▰▱ progress bars (were broken to ASCII)
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
    - budget_configs: List of dicts e.g.
        [{"category": "Food", "amount": 3000},
         {"category": "Total", "amount": 15000}]
      Use category "Total" for the overall monthly spending limit.
    """
    results = []
    for config in budget_configs:
        cat = config.get("category", "")
        amt = config.get("amount")
        try:
            if cat != "Total":
                cat = validate_category(cat)
            amt = validate_budget_amount(amt)
        except ValidationError as exc:
            results.append(f"⚠️ Skipped '{cat}': {exc}")
            continue

        upsert_budget(user_id, cat, amt)
        results.append(f"✅ {cat}: ₹{amt:,.0f}")

    if not results:
        return "No budgets were updated."
    return "Budgets updated:\n" + "\n".join(results)


@tool
def get_budget_report(user_id: int):
    """
    Shows current spending vs budgets with visual progress bars.
    """
    budgets = get_budgets(user_id)
    if not budgets:
        return "You haven't set any budgets yet. Tell me something like 'set food budget to ₹3000'."

    summary     = get_monthly_summary(user_id)
    total_spent = summary.get("expense", 0.0)

    report = ["📊 *Monthly Budget Report*\n"]

    for cat, limit in budgets.items():
        current = total_spent if cat == "Total" else get_category_monthly_spend(user_id, cat)
        percent = (current / limit * 100) if limit > 0 else 0

        if percent >= 100:
            status = "🚨"
        elif percent >= 80:
            status = "⚠️"
        else:
            status = "✅"

        bar_len = 10
        filled  = min(int(percent / 10), bar_len)
        bar     = "▰" * filled + "▱" * (bar_len - filled)

        report.append(f"{status} *{cat}*: ₹{current:,.0f} / ₹{limit:,.0f} ({percent:.1f}%)")
        report.append(f"   `{bar}`")

    return "\n".join(report)
