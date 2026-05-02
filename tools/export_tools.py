"""
tools/export_tools.py

Fixes applied:
  [4] Tool docstring now shows how to pass start_date/end_date for named months
      so the LLM knows to compute "2026-04-01"/"2026-04-30" for "april 2026"
      instead of refusing or offering alternatives.
"""

import os
import tempfile
import calendar
import re
import pytz
from datetime import datetime, timedelta
from langchain_core.tools import tool
import pandas as pd
from database.manager import get_filtered_expenses
from security.validators import (
    validate_export_format, validate_category, validate_type,
    ValidationError,
)

IST = pytz.timezone("Asia/Kolkata")

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _resolve_dates(start_date, end_date, period):
    """
    If start_date/end_date are not provided, resolve them from a period string.
    Returns (start_date, end_date) as YYYY-MM-DD strings or (None, None).
    """
    if start_date and end_date:
        return start_date, end_date

    if not period:
        return start_date, end_date

    now = datetime.now(IST)
    p = period.lower().strip()

    if "last month" in p:
        first_this  = now.replace(day=1)
        last_end    = first_this - timedelta(days=1)
        last_start  = last_end.replace(day=1)
        return last_start.strftime("%Y-%m-%d"), first_this.strftime("%Y-%m-%d")

    if "this month" in p:
        return now.replace(day=1).strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    if "this year" in p:
        return now.replace(month=1, day=1).strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    if "last year" in p:
        s = now.replace(year=now.year - 1, month=1, day=1)
        e = now.replace(month=1, day=1)
        return s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")

    # last N days/weeks/months
    m = re.search(r"last\s+(\d+)\s+(day|days|week|weeks|month|months)", p)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if "month" in unit:
            yr, mo = now.year, now.month - n
            while mo <= 0:
                mo += 12; yr -= 1
            s = now.replace(year=yr, month=mo, day=1)
        elif "week" in unit:
            s = now - timedelta(weeks=n)
        else:
            s = now - timedelta(days=n)
        return s.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # named month: "april", "april 2026"
    for mname, mnum in _MONTHS.items():
        if re.search(rf"\b{mname}\b", p):
            yr_m = re.search(r"\b(20\d{2})\b", p)
            yr   = int(yr_m.group(1)) if yr_m else now.year
            if yr == now.year and mnum > now.month:
                yr -= 1
            start = f"{yr}-{mnum:02d}-01"
            end   = f"{yr}-{mnum+1:02d}-01" if mnum < 12 else f"{yr+1}-01-01"
            return start, end

    return start_date, end_date


@tool
def export_expenses(
    user_id: int,
    format: str = "csv",
    category: str = None,
    start_date: str = None,
    end_date: str = None,
    type: str = None,
    period: str = None,
):
    """
    Exports transactions to a downloadable CSV or Excel file.

    - format:     'csv' or 'excel'.
    - category:   Optional filter e.g. 'Food', 'Transport'.
    - type:       Optional 'expense' or 'income'.
    - period:     Natural language period — use this instead of start/end dates when
                  the user says things like 'april', 'april 2026', 'last month',
                  'this year', 'last 3 months'. Examples:
                    period='april 2026'   → exports 1 Apr–30 Apr 2026
                    period='last month'   → exports the previous calendar month
                    period='this year'    → exports Jan 1 to today
    - start_date: YYYY-MM-DD (optional, overrides period if both given).
    - end_date:   YYYY-MM-DD (optional, overrides period if both given).

    When the user asks to export a specific month, set period='<month> <year>'
    e.g. period='april 2026'. Do NOT tell the user to provide dates themselves.
    """
    try:
        fmt = validate_export_format(format)
        if category: category = validate_category(category)
        if type:     type     = validate_type(type)
    except ValidationError as exc:
        return f"❌ Invalid input: {exc}"

    # Resolve dates from period if explicit dates not given
    start_date, end_date = _resolve_dates(start_date, end_date, period)

    rows = get_filtered_expenses(user_id, category, start_date, end_date, type)
    if not rows:
        label = period or (f"{start_date} to {end_date}" if start_date else "all time")
        return f"No transactions found for {label}."

    df = pd.DataFrame(rows, columns=["Amount", "Category", "Description", "Type", "Date"])

    suffix   = ".csv" if fmt == "csv" else ".xlsx"
    tmp      = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    filepath = tmp.name
    tmp.close()

    if fmt == "csv":
        df.to_csv(filepath, index=False)
    else:
        df.to_excel(filepath, index=False, engine="openpyxl")

    label = period or (f"{start_date} to {end_date}" if start_date else "all time")
    return f'✅ Export ready — {len(rows)} transactions for {label}.\nEXPORT_PATH:"{filepath}"'
