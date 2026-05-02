"""
tools/time_utils.py — Shared date/period utilities.

Single source of truth for:
  - _MONTHS dict (month name → number)
  - parse_period(period) → (start_date, end_date) YYYY-MM-DD strings
  - fmt_amount(amount) → "₹1,200" with no trailing .0 for whole numbers
  - fmt_datetime(iso_str) → "11 Apr 2026, 07:49 AM" IST

Previously duplicated verbatim across analytics_tools.py,
export_tools.py and financial_utils.py.
"""

import re
import calendar
from datetime import datetime, timedelta
from typing import Tuple, Optional
import pytz

IST = pytz.timezone("Asia/Kolkata")

MONTHS: dict = {
    "january": 1,  "february": 2,  "march": 3,    "april": 4,
    "may": 5,      "june": 6,      "july": 7,      "august": 8,
    "september": 9,"october": 10,  "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_period(period: str) -> Tuple[str, str]:
    """
    Convert any natural-language period string to (start, end) in YYYY-MM-DD.

    Supported patterns
    ──────────────────
    today · yesterday
    this week · last week
    this month · last month
    this year · last year
    last N days / weeks / months
    <month>              e.g. "april"        → Apr of current or previous year
    <month> <year>       e.g. "april 2026"  → Apr 2026
    YYYY-MM-DD           passed through as a single-day range
    """
    now = datetime.now(IST)
    t   = period.lower().strip()

    # ── Explicit date ─────────────────────────────────────────────────────────
    if re.match(r"^\d{4}-\d{2}-\d{2}$", t):
        return t, t

    # ── today ─────────────────────────────────────────────────────────────────
    if t == "today":
        s = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return s.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # ── yesterday ─────────────────────────────────────────────────────────────
    if t == "yesterday":
        y = now - timedelta(days=1)
        return y.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")

    # ── this week ─────────────────────────────────────────────────────────────
    if "this week" in t:
        s = now - timedelta(days=now.weekday())
        return s.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # ── last week ─────────────────────────────────────────────────────────────
    if "last week" in t:
        s = now - timedelta(days=now.weekday() + 7)
        e = now - timedelta(days=now.weekday())
        return s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")

    # ── this month / current month ────────────────────────────────────────────
    if "this month" in t or "current month" in t:
        s = now.replace(day=1)
        return s.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # ── last month ────────────────────────────────────────────────────────────
    if "last month" in t:
        first_this  = now.replace(day=1)
        last_end    = first_this - timedelta(days=1)
        last_start  = last_end.replace(day=1)
        return last_start.strftime("%Y-%m-%d"), first_this.strftime("%Y-%m-%d")

    # ── this year ─────────────────────────────────────────────────────────────
    if "this year" in t:
        s = now.replace(month=1, day=1)
        return s.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # ── last year ─────────────────────────────────────────────────────────────
    if "last year" in t:
        s = now.replace(year=now.year - 1, month=1, day=1)
        e = now.replace(month=1, day=1)
        return s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")

    # ── last N days / weeks / months ─────────────────────────────────────────
    m = re.search(r"last\s+(\d+)\s+(day|days|week|weeks|month|months)", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if "month" in unit:
            yr, mo = now.year, now.month - n
            while mo <= 0:
                mo += 12
                yr -= 1
            s = now.replace(year=yr, month=mo, day=1)
        elif "week" in unit:
            s = now - timedelta(weeks=n)
        else:
            s = now - timedelta(days=n)
        return s.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # ── Named month (with optional year) ─────────────────────────────────────
    for mname, mnum in MONTHS.items():
        if re.search(rf"\b{mname}\b", t):
            yr_m = re.search(r"\b(20\d{2})\b", t)
            yr   = int(yr_m.group(1)) if yr_m else now.year
            if yr == now.year and mnum > now.month:
                yr -= 1
            start = f"{yr}-{mnum:02d}-01"
            end   = f"{yr}-{mnum+1:02d}-01" if mnum < 12 else f"{yr+1}-01-01"
            return start, end

    # ── Fallback: this month ──────────────────────────────────────────────────
    s = now.replace(day=1)
    return s.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")


def period_label(period: str) -> str:
    """Return a human-friendly title for a period string, e.g. 'April 2026'."""
    t = period.lower().strip()
    for mname, mnum in MONTHS.items():
        if re.search(rf"\b{mname}\b", t):
            yr_m = re.search(r"\b(20\d{2})\b", t)
            yr   = int(yr_m.group(1)) if yr_m else datetime.now(IST).year
            return f"{calendar.month_name[mnum]} {yr}"
    return period.title()


def fmt_amount(amount) -> str:
    """
    Format a monetary amount with ₹ symbol.
    Whole numbers show no decimal: ₹200 not ₹200.0
    Fractional amounts show 2 dp: ₹241.50
    """
    amount = float(amount)
    if amount == int(amount):
        return f"₹{int(amount):,}"
    return f"₹{amount:,.2f}"


def fmt_datetime(iso_str: str) -> str:
    """
    Convert a raw ISO 8601 / Supabase timestamp to a readable IST string.
    Input:  "2026-04-11T07:49:00+05:30" or "2026-04-11T02:19:00+00:00"
    Output: "11 Apr 2026, 07:49 AM"
    """
    try:
        # Handle both offset-aware and naive strings
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = IST.localize(dt)
        else:
            dt = dt.astimezone(IST)
        return dt.strftime("%-d %b %Y, %I:%M %p")
    except Exception:
        return iso_str[:16]  # fallback: trim to "2026-04-11T07:49"


def validate_date_str(value: Optional[str], field: str) -> Optional[str]:
    """
    [7] Security: validate that a date string is YYYY-MM-DD before
    it reaches the DB.  Rejects anything that could be a SQL fragment.
    Returns the validated string or None.
    """
    if value is None:
        return None
    value = str(value).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        from security.validators import ValidationError
        raise ValidationError(
            f"'{field}' must be in YYYY-MM-DD format, got '{value}'."
        )
    # Range check
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        from security.validators import ValidationError
        raise ValidationError(f"'{field}' is not a valid date: '{value}'.")
    return value
