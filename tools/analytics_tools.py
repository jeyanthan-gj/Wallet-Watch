"""
tools/analytics_tools.py

Fixes applied:
  [1] _get_date_range() completely rewritten — handles:
      - Named months: "april", "april 2026", "last month"
      - Relative: "yesterday", "last week", "last 3 months"
      - Presets: "today", "this week", "this month", "this year"
      - Explicit YYYY-MM-DD ranges passed directly
  [2] Line chart KeyError fixed — date column assigned on expenses df
  Security: charts written to tempfile, cleaned up by main.py after send.
"""

import os
import re
import tempfile
import calendar
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime, timedelta
from langchain_core.tools import tool
from database.manager import get_expenses_in_range
from security.validators import validate_chart_type, ValidationError
import pytz

IST = pytz.timezone("Asia/Kolkata")

# Month name → number mapping
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _get_date_range(timeframe: str):
    """
    Converts any natural-language timeframe into (start_date, end_date) strings
    in YYYY-MM-DD format.

    Supported patterns:
      today, yesterday
      this week, last week
      this month, last month
      this year, last year
      last N days / last N months / last N weeks
      <month name> e.g. "april" → April of current/past year
      <month name> <year> e.g. "april 2026"
      YYYY-MM-DD (passed directly as start — uses full day)
    """
    now = datetime.now(IST)
    t = timeframe.lower().strip()

    # ── Explicit single date YYYY-MM-DD ───────────────────────────────────────
    if re.match(r"^\d{4}-\d{2}-\d{2}$", t):
        return t, t

    # ── today ─────────────────────────────────────────────────────────────────
    if t in ("today",):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end   = now + timedelta(days=1)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    # ── yesterday ─────────────────────────────────────────────────────────────
    if t in ("yesterday",):
        yesterday = now - timedelta(days=1)
        return yesterday.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")

    # ── this week ─────────────────────────────────────────────────────────────
    if "this week" in t:
        start = now - timedelta(days=now.weekday())
        return start.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # ── last week ─────────────────────────────────────────────────────────────
    if "last week" in t:
        start = now - timedelta(days=now.weekday() + 7)
        end   = now - timedelta(days=now.weekday())
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    # ── this month ────────────────────────────────────────────────────────────
    if "this month" in t:
        start = now.replace(day=1)
        return start.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # ── last month ────────────────────────────────────────────────────────────
    if "last month" in t:
        first_of_this = now.replace(day=1)
        last_month_end = first_of_this - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        # +1 day on end so the final day is included in gte/lte queries
        return (
            last_month_start.strftime("%Y-%m-%d"),
            first_of_this.strftime("%Y-%m-%d"),
        )

    # ── this year / last year ─────────────────────────────────────────────────
    if "this year" in t:
        start = now.replace(month=1, day=1)
        return start.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")
    if "last year" in t:
        start = now.replace(year=now.year - 1, month=1, day=1)
        end   = now.replace(month=1, day=1)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    # ── last N days / weeks / months ─────────────────────────────────────────
    m = re.search(r"last\s+(\d+)\s+(day|days|week|weeks|month|months)", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if "month" in unit:
            # Go back N months
            year  = now.year
            month = now.month - n
            while month <= 0:
                month += 12
                year  -= 1
            start = now.replace(year=year, month=month, day=1)
        elif "week" in unit:
            start = now - timedelta(weeks=n)
        else:
            start = now - timedelta(days=n)
        return start.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # ── Named month (with optional year): "april", "april 2026", "apr 2025" ──
    for month_name, month_num in _MONTHS.items():
        pattern = rf"\b{month_name}\b"
        if re.search(pattern, t):
            # Extract year if present
            year_match = re.search(r"\b(20\d{2})\b", t)
            year = int(year_match.group(1)) if year_match else now.year
            # If named month is in the future this year, use last year
            if year == now.year and month_num > now.month:
                year -= 1
            last_day = calendar.monthrange(year, month_num)[1]
            start = f"{year}-{month_num:02d}-01"
            # end is first day of next month (exclusive upper bound)
            if month_num == 12:
                end = f"{year + 1}-01-01"
            else:
                end = f"{year}-{month_num + 1:02d}-01"
            return start, end

    # ── Fallback: last 30 days ────────────────────────────────────────────────
    start = now - timedelta(days=30)
    return start.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")


def _nice_title(timeframe: str) -> str:
    """Human-friendly chart title for any timeframe string."""
    t = timeframe.lower().strip()
    for month_name, month_num in _MONTHS.items():
        if re.search(rf"\b{month_name}\b", t):
            year_match = re.search(r"\b(20\d{2})\b", t)
            now = datetime.now(IST)
            year = int(year_match.group(1)) if year_match else now.year
            return f"{calendar.month_name[month_num]} {year}"
    return timeframe.title()


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
        return f"Invalid input: {exc}"

    start_date, end_date = _get_date_range(timeframe)
    data = get_expenses_in_range(user_id, start_date, end_date)

    if not data:
        title = _nice_title(timeframe)
        return f"No transactions found for {title} ({start_date} to {end_date})."

    df = pd.DataFrame(data, columns=["amount", "category", "description", "type", "created_at"])
    df["amount"] = pd.to_numeric(df["amount"])

    title = _nice_title(timeframe)

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
            expenses = df[df["type"] == "expense"].copy()   # FIX: work on copy
            if expenses.empty:
                os.remove(filepath)
                return f"No expenses found for {title} to create a line chart."
            # FIX: assign date on the expenses df, not the full df
            expenses["date"] = pd.to_datetime(expenses["created_at"]).dt.date
            daily = expenses.groupby("date")["amount"].sum()
            daily.plot(kind="line", marker="o", color="tab:red", linewidth=2)
            plt.title(f"Daily Spending Trend — {title}")
            plt.xlabel("Date")
            plt.ylabel("Amount (₹)")
            plt.grid(True, linestyle="--", alpha=0.7)
            # Rotate x labels for readability on longer date ranges
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
