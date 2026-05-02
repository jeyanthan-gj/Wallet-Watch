"""
tools/export_tools.py — CSV / Excel export tool.
Uses shared parse_period / period_label / validate_date_str from tools/time_utils.py.
"""

import os
import tempfile
import pandas as pd
from datetime import datetime
from langchain_core.tools import tool
from database.manager import get_filtered_expenses
from security.validators import validate_export_format, validate_category, validate_type, ValidationError
from tools.time_utils import parse_period, period_label, validate_date_str, fmt_datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")


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
    - period:     Natural language period — use this for named months/ranges:
                    period='april 2026'   → exports 1 Apr–30 Apr 2026
                    period='last month'   → exports the previous calendar month
                    period='this year'    → exports Jan 1 to today
                    period='last 3 months'
    - start_date: YYYY-MM-DD (optional, overrides period if both given).
    - end_date:   YYYY-MM-DD (optional, overrides period if both given).

    ALWAYS use period= for natural language requests.
    Do NOT ask the user for date strings — resolve them automatically.
    """
    try:
        fmt = validate_export_format(format)
        if category:   category   = validate_category(category)
        if type:       type       = validate_type(type)
        if start_date: start_date = validate_date_str(start_date, "start_date")
        if end_date:   end_date   = validate_date_str(end_date,   "end_date")
    except ValidationError as exc:
        return f"❌ Invalid input: {exc}"

    # Resolve natural language period if explicit dates not provided
    if not (start_date and end_date) and period:
        start_date, end_date = parse_period(period)

    rows = get_filtered_expenses(user_id, category, start_date, end_date, type)
    if not rows:
        label = period_label(period) if period else (
            f"{start_date} to {end_date}" if start_date else "all time"
        )
        return f"No transactions found for {label}."

    # [8] Clean up dates for export — convert ISO to human-readable IST
    cleaned = []
    for amount, cat, desc, ttype, created_at in rows:
        cleaned.append({
            "Amount (₹)":    float(amount),
            "Category":      cat,
            "Description":   desc or "",
            "Type":          ttype,
            "Date":          fmt_datetime(created_at),
        })
    df = pd.DataFrame(cleaned)

    suffix   = ".csv" if fmt == "csv" else ".xlsx"
    tmp      = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    filepath = tmp.name
    tmp.close()

    if fmt == "csv":
        df.to_csv(filepath, index=False)
    else:
        df.to_excel(filepath, index=False, engine="openpyxl")

    label = period_label(period) if period else (
        f"{start_date} to {end_date}" if start_date else "all time"
    )
    return f'✅ Export ready — {len(rows)} transactions for {label}.\nEXPORT_PATH:"{filepath}"'
