"""
tools/analytics_tools.py — Chart generation tool.
Uses shared parse_period / period_label from tools/time_utils.py.
"""

import os
import tempfile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from langchain_core.tools import tool
from database.manager import get_expenses_in_range
from security.validators import validate_chart_type, ValidationError
from tools.time_utils import parse_period, period_label, fmt_amount


@tool
def generate_chart(user_id: int, chart_type: str, timeframe: str):
    """
    Generates a financial chart and sends it as an image.

    - chart_type: 'pie' (spending by category), 'line' (daily trend),
                  or 'bar' (income vs expense).
    - timeframe:  ANY natural language period. Examples:
                  'today', 'yesterday', 'this week', 'last week',
                  'this month', 'last month', 'this year', 'last year',
                  'april', 'april 2026', 'march 2025',
                  'last 3 months', 'last 7 days', 'last 2 weeks'.
                  ALWAYS pass the user's intended period directly —
                  never tell the user it's unsupported.
    """
    try:
        chart_type = validate_chart_type(chart_type)
    except ValidationError as exc:
        return f"❌ Invalid input: {exc}"

    start_date, end_date = parse_period(timeframe)
    data = get_expenses_in_range(user_id, start_date, end_date)
    title = period_label(timeframe)

    if not data:
        return f"No transactions found for {title} ({start_date} to {end_date})."

    df = pd.DataFrame(data, columns=["amount", "category", "description", "type", "created_at"])
    df["amount"] = pd.to_numeric(df["amount"])

    tmp      = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    filepath = tmp.name
    tmp.close()

    plt.figure(figsize=(10, 6))
    try:
        if chart_type == "pie":
            expenses = df[df["type"] == "expense"]
            if expenses.empty:
                os.remove(filepath)
                return f"No expenses found for {title} to create a pie chart."
            expenses.groupby("category")["amount"].sum().plot(
                kind="pie", autopct="%1.1f%%", startangle=140, colormap="viridis"
            )
            plt.title(f"Spending Breakdown — {title}")
            plt.ylabel("")

        elif chart_type == "line":
            expenses = df[df["type"] == "expense"].copy()
            if expenses.empty:
                os.remove(filepath)
                return f"No expenses found for {title} to create a line chart."
            expenses["date"] = pd.to_datetime(expenses["created_at"]).dt.date
            expenses.groupby("date")["amount"].sum().plot(
                kind="line", marker="o", color="tab:red", linewidth=2
            )
            plt.title(f"Daily Spending Trend — {title}")
            plt.xlabel("Date")
            plt.ylabel("Amount (₹)")
            plt.grid(True, linestyle="--", alpha=0.7)
            plt.xticks(rotation=45, ha="right")

        elif chart_type == "bar":
            type_totals = df.groupby("type")["amount"].sum()
            colors = ["tab:green" if t == "income" else "tab:red" for t in type_totals.index]
            type_totals.plot(kind="bar", color=colors)
            plt.title(f"Income vs Expenses — {title}")
            plt.ylabel("Amount (₹)")
            plt.xticks(rotation=0)

        plt.tight_layout()
        plt.savefig(filepath, dpi=150)
        plt.close()
        return f'CHART_PATH:"{filepath}"'

    except Exception as exc:
        plt.close()
        try:
            os.remove(filepath)
        except OSError:
            pass
        return f"Error generating chart: {type(exc).__name__}: {exc}"
