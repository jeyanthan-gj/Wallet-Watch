"""
tools/report_generator.py

[10] Morning report amounts now formatted via fmt_amount — no trailing .0
"""

import random
import logging
from database.manager import (
    get_monthly_summary, get_budgets, get_category_monthly_spend,
    get_user_first_name,
)
from tools.time_utils import fmt_amount

logger = logging.getLogger(__name__)


def generate_morning_report(user_id: int) -> str:
    """Generates a personalised financial summary for the user."""
    first_name = get_user_first_name(user_id)

    try:
        summary = get_monthly_summary(user_id)
        income  = summary.get("income",  0.0)
        expense = summary.get("expense", 0.0)
        balance = income - expense
        budgets = get_budgets(user_id)
    except Exception as exc:
        logger.error("Morning report data fetch failed for user %d: %s", user_id, exc)
        return (
            f"Good morning, {first_name}! ☀️\n\n"
            "Couldn't load your financial snapshot right now. Try again later."
        )

    greetings = [
        f"Good morning, {first_name}! ☀️",
        f"Namaste {first_name}! Hope you have a great day. 🙏",
        f"Rise and shine, {first_name}! ✨",
    ]

    report = [random.choice(greetings)]
    report.append("\n📊 *Daily Financial Snapshot*")
    report.append(f"• Income this month:  {fmt_amount(income)}")
    report.append(f"• Spent this month:   {fmt_amount(expense)}")

    if income > 0:
        if balance >= 0:
            report.append(f"• Remaining Balance:  {fmt_amount(balance)}")
        else:
            report.append(f"• Deficit this month: {fmt_amount(abs(balance))} 🚩")

    if budgets:
        report.append("\n🎯 *Budget Progress:*")
        for cat, limit in budgets.items():
            current = expense if cat == "Total" else get_category_monthly_spend(user_id, cat)
            percent = (current / limit * 100) if limit > 0 else 0
            if percent >= 100:
                report.append(f"🚨 EXCEEDED: {fmt_amount(current)} / {fmt_amount(limit)} on {cat}!")
            elif percent >= 80:
                report.append(f"⚠️ {cat}: {percent:.1f}% used ({fmt_amount(current)} / {fmt_amount(limit)})")
            elif percent >= 50:
                report.append(f"ℹ️ {cat}: {percent:.1f}% used")

    tips = [
        "Pro tip: Try to save 20% of your income this month! 📈",
        "Reminder: Tracking small expenses like coffee adds up to big savings. ☕",
        "Check your recurring bills for unused subscriptions! 🔍",
        "Investing even a small amount regularly can build wealth over time. 💎",
    ]
    report.append(f"\n💡 {random.choice(tips)}")
    report.append("\nHave a productive day! 🚀")

    return "\n".join(report)
