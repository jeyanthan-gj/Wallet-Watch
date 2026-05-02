"""
Input validation for all tool arguments.

Every public-facing value that comes from a user message (via the LLM)
must pass through a validator before hitting the database.

Rules:
  - Amounts must be positive and capped at a sane maximum.
  - type must be exactly 'expense' or 'income'.
  - Strings are stripped and length-capped (prevents DoS via huge payloads).
  - category values are normalised to Title Case to avoid duplicates.
  - No HTML/script content is allowed in free-text fields.
"""

import re
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_AMOUNT          = 10_000_000        # ₹1 crore — hard ceiling
MAX_DESC_LEN        = 200               # characters
MAX_CATEGORY_LEN    = 50
VALID_TYPES         = {"expense", "income"}
VALID_CHART_TYPES   = {"pie", "line", "bar"}
VALID_EXPORT_FMTS   = {"csv", "excel"}

# Characters we never want stored (basic XSS / injection defence)
_DANGEROUS_RE = re.compile(r"[<>\"'`;]")


class ValidationError(ValueError):
    """Raised when a tool argument fails validation."""


def _strip(value: Optional[str], max_len: int, field: str) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    # Remove dangerous characters
    value = _DANGEROUS_RE.sub("", value)
    if len(value) > max_len:
        raise ValidationError(
            f"'{field}' is too long (max {max_len} characters)."
        )
    return value


def validate_amount(amount) -> float:
    """Amount must be a positive number ≤ MAX_AMOUNT."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        raise ValidationError("Amount must be a number.")
    if amount <= 0:
        raise ValidationError("Amount must be greater than zero.")
    if amount > MAX_AMOUNT:
        raise ValidationError(
            f"Amount ₹{amount:,.0f} exceeds the maximum allowed (₹{MAX_AMOUNT:,.0f})."
        )
    return round(amount, 2)


def validate_type(ttype: str) -> str:
    """Transaction type must be 'expense' or 'income'."""
    if not ttype or ttype.lower() not in VALID_TYPES:
        raise ValidationError(
            f"Type must be 'expense' or 'income', got '{ttype}'."
        )
    return ttype.lower()


def validate_category(category: Optional[str]) -> str:
    """Category: strip, cap length, Title Case."""
    cat = _strip(category, MAX_CATEGORY_LEN, "category")
    if not cat:
        raise ValidationError("Category cannot be empty.")
    return cat.title()          # "food" → "Food", "FOOD" → "Food"


def validate_description(description: Optional[str]) -> str:
    """Description: strip and cap length. Empty is allowed."""
    return _strip(description, MAX_DESC_LEN, "description")


def validate_chart_type(chart_type: str) -> str:
    if not chart_type or chart_type.lower() not in VALID_CHART_TYPES:
        raise ValidationError(
            f"chart_type must be one of {VALID_CHART_TYPES}, got '{chart_type}'."
        )
    return chart_type.lower()


def validate_export_format(fmt: str) -> str:
    if not fmt or fmt.lower() not in VALID_EXPORT_FMTS:
        raise ValidationError(
            f"format must be 'csv' or 'excel', got '{fmt}'."
        )
    return fmt.lower()


def validate_day_of_month(day) -> int:
    try:
        day = int(day)
    except (TypeError, ValueError):
        raise ValidationError("day_of_month must be an integer.")
    if not (1 <= day <= 28):        # cap at 28 to avoid Feb/month-end issues
        raise ValidationError("day_of_month must be between 1 and 28.")
    return day


def validate_installments(n) -> Optional[int]:
    if n is None:
        return None
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise ValidationError("installments must be a positive integer.")
    if n <= 0 or n > 600:           # 50 years max
        raise ValidationError("installments must be between 1 and 600.")
    return n


def validate_interval(n) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise ValidationError("interval must be a positive integer.")
    if n <= 0 or n > 24:
        raise ValidationError("interval must be between 1 and 24 months.")
    return n


def validate_limit(n, default: int = 10, max_val: int = 50) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return default
    return max(1, min(n, max_val))


def validate_transaction_id(tid) -> int:
    try:
        tid = int(tid)
    except (TypeError, ValueError):
        raise ValidationError("Transaction ID must be an integer.")
    if tid <= 0:
        raise ValidationError("Transaction ID must be positive.")
    return tid


def validate_budget_amount(amount) -> float:
    """Budget amounts follow same rules as transaction amounts."""
    return validate_amount(amount)


def validate_keyword(keyword: Optional[str]) -> Optional[str]:
    if not keyword:
        return None
    kw = _strip(keyword, 100, "keyword")
    return kw if kw else None
