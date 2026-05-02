"""
tools/report_generator.py

FIX: generate_morning_report now fetches first_name from the users table
     instead of receiving it as a parameter with a useless default "there".
"""

import random
import logging
from database.manager import (
    get_monthly_summary, get_budgets, get_category_monthly_spend,
    get_total_spent, get_user_first_name,
)

logger = logging.getLogger(__name__)


def generate_morning_report(user_id: int) -> str:
    """Generates a personalised financial summary for the user."""
    # FIX: fetch actual name from DB instead of defaulting to "there"
    first_name = get_user_first_name(user_id)

    try:
        summary = get_monthly_summary(user_id)
        income  = summary.get("income",  0.0)
        expense = summary.get("expense", 0.0)
        balance = income - expense
        budgets = get_budgets(user_id)
    except Exception as exc:
        logger.error("Morning report data fetch failed for user %d: %s", user_id, exc)
        return f"Good morning, {first_name}! ☀️\n\nCouldn't load your financial snapshot right now. Try again later."

    greetings = [
        f"Good morning, {first_name}! ☀️",
        f"Namaste {first_name}! Hope you have a great day. 🙏",
        f"Rise and shine, {first_name}! ✨",
    ]

    report = [random.choice(greetings)]
    report.append("\n📊 *Daily Financial Snapshot*")
    report.append(f"• Income this month: ₹{income:,.2f}")
    report.append(f"• Spent this month: ₹{expense:,.2f}")

    if income > 0:
        report.append(f"• Remaining Balance: ₹{balance:,.2f}")

    if budgets:
        report.append("\n🎯 *Budget Progress:*")
        for cat, limit in budgets.items():
            current = expense if cat == "Total" else get_category_monthly_spend(user_id, cat)
            percent = (current / limit * 100) if limit > 0 else 0
            if percent >= 80:
                report.append(f"⚠️ Warning: You've used {percent:.1f}% of your {cat} budget!")
            elif percent >= 50:
                report.append(f"ℹ️ Note: You're at {percent:.1f}% for your {cat} budget.")

    tips = [
        "Pro tip: Try to save 20% of your income this month! 📈",
        "Reminder: Tracking small expenses like coffee adds up to big savings. ☕",
        "Check your recurring bills for unused subscriptions! 🔍",
        "Investing even a small amount regularly can build wealth over time. 💎",
    ]
    report.append(f"\n💡 {random.choice(tips)}")
    report.append("\nHave a productive day! 🚀")

    return "\n".join(report)
