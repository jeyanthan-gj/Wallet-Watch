"""
tools/export_tools.py

Security hardening applied:
  [HIGH-7] Export files are written to a secure temp path using Python's
           tempfile module instead of a predictable exports/ directory.
           Files are cleaned up by main.py immediately after being sent.
  [CRIT-4] format, category, type inputs are validated.
"""

import os
import tempfile
import pandas as pd
from datetime import datetime
from langchain_core.tools import tool
from database.manager import get_filtered_expenses
from security.validators import (
    validate_export_format, validate_category, validate_type,
    ValidationError,
)


@tool
def export_expenses(
    user_id: int,
    format: str = "csv",
    category: str = None,
    start_date: str = None,
    end_date: str = None,
    type: str = None,
):
    """
    Exports expenses to a file (CSV or Excel) based on user filters.
    - user_id:     The ID of the user.
    - format:      'csv' or 'excel'.
    - category:    Optional category filter.
    - start_date:  Optional start date (YYYY-MM-DD).
    - end_date:    Optional end date (YYYY-MM-DD).
    - type:        Optional 'expense' or 'income'.
    """
    try:
        fmt = validate_export_format(format)
        if category: category = validate_category(category)
        if type:     type     = validate_type(type)
    except ValidationError as exc:
        return f"Invalid input: {exc}"

    rows = get_filtered_expenses(user_id, category, start_date, end_date, type)
    if not rows:
        return "No data found for the specified filters."

    df = pd.DataFrame(rows, columns=["Amount", "Category", "Description", "Type", "Date"])

    # [HIGH-7] Use a temp file with a non-guessable name, not exports/{user_id}_...
    suffix = ".csv" if fmt == "csv" else ".xlsx"
    tmp    = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    filepath = tmp.name
    tmp.close()

    if fmt == "csv":
        df.to_csv(filepath, index=False)
    else:
        df.to_excel(filepath, index=False, engine="openpyxl")

    return f'Export successful! Here is your {fmt} file.\nEXPORT_PATH:"{filepath}"'
