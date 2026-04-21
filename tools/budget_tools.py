from typing import List, Dict
from langchain_core.tools import tool
from database.manager import upsert_budget, get_budgets, get_monthly_summary, get_category_monthly_spend

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
        cat = config.get("category")
        amt = config.get("amount")
        upsert_budget(user_id, cat, amt)
        results.append(f"{cat}: ${amt}")
    
    return f"Successfully updated budgets:\n" + "\n".join(results)

@tool
def get_budget_report(user_id: int):
    """
    Generates a report of current spending vs budgets.
    """
    budgets = get_budgets(user_id)
    if not budgets:
        return "You haven't set any budgets yet. Use 'manage_budgets' to get started!"
    
    summary = get_monthly_summary(user_id)
    total_spent = summary.get("expense", 0.0)
    
    report = ["📊 *Monthly Budget Report*"]
    
    for cat, limit in budgets.items():
        if cat == "Total":
            current = total_spent
        else:
            current = get_category_monthly_spend(user_id, cat)
            
        percent = (current / limit) * 100 if limit > 0 else 0
        status_emoji = "✅" if percent < 80 else "⚠️" if percent < 100 else "🚨"
        
        report.append(f"{status_emoji} *{cat}*: ${current} / ${limit} ({percent:.1f}%)")
        # Simple progress bar
        bar_len = 10
        filled = min(int(percent / 10), bar_len)
        bar = "▰" * filled + "▱" * (bar_len - filled)
        report.append(f"   `{bar}`")

    return "\n".join(report)
