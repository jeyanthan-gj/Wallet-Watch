from database.manager import get_monthly_summary, get_budgets, get_category_monthly_spend, get_total_spent
import random

def generate_morning_report(user_id: int, first_name: str = "there"):
    """Generates a personalized financial summary for the user."""
    summary = get_monthly_summary(user_id)
    income = summary.get("income", 0.0)
    expense = summary.get("expense", 0.0)
    balance = income - expense
    
    budgets = get_budgets(user_id)
    
    # Greetings
    greetings = [
        f"Good morning, {first_name}! ☀️",
        f"Namaste {first_name}! Hope you have a great day. 🙏",
        f"Rise and shine, {first_name}! ✨"
    ]
    report = [random.choice(greetings)]
    report.append("\n📊 *Daily Financial Snapshot*")
    report.append(f"• Income this month: ₹{income:,.2f}")
    report.append(f"• Spent this month: ₹{expense:,.2f}")
    
    if income > 0:
        report.append(f"• Remaining Balance: ₹{balance:,.2f}")

    # Budget Status Check
    if budgets:
        report.append("\n🎯 *Budget Progress:*")
        for cat, limit in budgets.items():
            if cat == "Total":
                current = expense
            else:
                current = get_category_monthly_spend(user_id, cat)
            
            percent = (current / limit) * 100 if limit > 0 else 0
            if percent >= 80:
                report.append(f"⚠️ Warning: You've used {percent:.1f}% of your {cat} budget!")
            elif percent >= 50:
                report.append(f"ℹ️ Note: You're at {percent:.1f}% for your {cat} budget.")

    # Financial Tip
    tips = [
        "Pro tip: Try to save 20% of your income this month! 📈",
        "Reminder: Tracking small expenses like coffee adds up to big savings. ☕",
        "Check your recurring bills to see if you have any unused subscriptions! 🔍",
        "Investing even a small amount regularly can build wealth over time. 💎"
    ]
    report.append(f"\n💡 {random.choice(tips)}")
    
    report.append("\nHave a productive day! 🚀")
    return "\n".join(report)
