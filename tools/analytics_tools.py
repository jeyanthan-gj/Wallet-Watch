"""
tools/analytics_tools.py

Security hardening applied:
  [HIGH-7] Charts written to tempfile, not predictable exports/ path.
           main.py deletes the file immediately after sending.
  [CRIT-4] chart_type validated against allowlist before use.
"""

import os
import tempfile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime, timedelta
from langchain_core.tools import tool
from database.manager import get_expenses_in_range
from security.validators import validate_chart_type, ValidationError
import pytz
from dateutil import parser as dateutil_parser

IST = pytz.timezone("Asia/Kolkata")


def _get_date_range(timeframe: str):
    now = datetime.now(IST)
    t   = timeframe.lower().strip()
    end_date = now + timedelta(days=1)

    if "today"  in t: start_date = now
    elif "week" in t: start_date = now - timedelta(days=7)
    elif "month" in t: start_date = now.replace(day=1)
    elif "year"  in t: start_date = now.replace(month=1, day=1)
    else:
        try:
            parsed     = dateutil_parser.parse(t, fuzzy=True, default=now)
            start_date = parsed
            end_date   = parsed + timedelta(days=1)
        except Exception:
            start_date = now - timedelta(days=30)

    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


@tool
def generate_chart(user_id: int, chart_type: str, timeframe: str):
    """
    Generates a financial chart.
    - chart_type: 'pie' (category breakdown), 'line' (trend), or 'bar' (income vs expense).
    - timeframe:  Natural language: 'today', 'this week', 'this month', 'this year'.
    """
    try:
        chart_type = validate_chart_type(chart_type)
    except ValidationError as exc:
        return f"Invalid input: {exc}"

    start_date, end_date = _get_date_range(timeframe)
    data = get_expenses_in_range(user_id, start_date, end_date)

    if not data:
        return f"No transaction data found for {timeframe} ({start_date} to {end_date})."

    df = pd.DataFrame(data, columns=["amount", "category", "description", "type", "created_at"])
    df["amount"] = pd.to_numeric(df["amount"])

    # [HIGH-7] Temp file — unpredictable path, cleaned up by main.py after send
    tmp      = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    filepath = tmp.name
    tmp.close()

    plt.figure(figsize=(10, 6))
    try:
        if chart_type == "pie":
            expenses = df[df["type"] == "expense"]
            if expenses.empty:
                return "No expenses found to create a pie chart."
            expenses.groupby("category")["amount"].sum().plot(
                kind="pie", autopct="%1.1f%%", startangle=140, colormap="viridis"
            )
            plt.title(f"Spending Breakdown ({timeframe})")
            plt.ylabel("")

        elif chart_type == "line":
            expenses = df[df["type"] == "expense"]
            if expenses.empty:
                return "No expenses found to create a trend line."
            df["date"] = pd.to_datetime(df["created_at"]).dt.date
            expenses.groupby("date")["amount"].sum().plot(
                kind="line", marker="o", color="tab:red", linewidth=2
            )
            plt.title(f"Spending Trend ({timeframe})")
            plt.xlabel("Date")
            plt.ylabel("Amount (Rs)")
            plt.grid(True, linestyle="--", alpha=0.7)

        elif chart_type == "bar":
            df.groupby("type")["amount"].sum().plot(
                kind="bar", color=["tab:red", "tab:green"]
            )
            plt.title(f"Income vs Expenses ({timeframe})")
            plt.ylabel("Amount (Rs)")
            plt.xticks(rotation=0)

        plt.tight_layout()
        plt.savefig(filepath)
        plt.close()
        return f'CHART_PATH:"{filepath}"'

    except Exception as exc:
        plt.close()
        try:
            os.remove(filepath)
        except OSError:
            pass
        return f"Error generating chart: {type(exc).__name__}"
