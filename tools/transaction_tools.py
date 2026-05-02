"""
tools/transaction_tools.py — Search, delete, edit transactions.
All amounts now formatted with ₹ via fmt_amount. Markdown-safe output.
"""

from langchain_core.tools import tool
from database.manager import (
    get_transaction_by_id, search_transactions_db,
    delete_transaction_db, update_transaction_db,
)
from security.validators import (
    validate_amount, validate_type, validate_category, validate_description,
    validate_keyword, validate_limit, validate_transaction_id, ValidationError,
)
from security.audit_log import log_transaction_delete, log_transaction_edit
from tools.time_utils import fmt_amount, fmt_datetime


@tool
def search_transactions(user_id: int, keyword: str = None, category: str = None, limit: int = 10):
    """
    Searches recent transactions to find IDs for editing or deleting.
    - keyword:  Optional text in description (e.g. 'lunch', 'netflix').
    - category: Optional category filter (e.g. 'Food', 'Entertainment').
    - limit:    Max results (default 10, max 50).
    Always call this before delete_transaction or edit_transaction.
    """
    try:
        keyword  = validate_keyword(keyword)
        category = validate_category(category) if category else None
        limit    = validate_limit(limit)
    except ValidationError as exc:
        return f"❌ Invalid input: {exc}"

    rows = search_transactions_db(user_id, keyword=keyword, category=category, limit=limit)
    if not rows:
        return "No matching transactions found. Try a different keyword or category."

    lines = ["🔍 *Matching Transactions:*\n"]
    for tid, amount, cat, desc, ttype, created_at in rows:
        sign     = "−" if ttype == "expense" else "+"
        date_str = fmt_datetime(created_at)
        lines.append(f"*#{tid}* | {sign}{fmt_amount(amount)} | {cat} | {desc or '—'} | {date_str}")
    lines.append("\n_Reply with the # number to delete or edit._")
    return "\n".join(lines)


@tool
def delete_transaction(user_id: int, transaction_id: int):
    """
    Permanently deletes a transaction by its ID.
    IMPORTANT: Always search first, show the result, and ask for explicit
    confirmation before calling this tool.
    - user_id:         Ownership verified at the DB layer.
    - transaction_id:  Numeric ID from search_transactions.
    """
    try:
        transaction_id = validate_transaction_id(transaction_id)
    except ValidationError as exc:
        return f"❌ Invalid input: {exc}"

    row = get_transaction_by_id(user_id, transaction_id)
    if not row:
        return f"❌ Transaction #{transaction_id} not found or does not belong to you."

    tid, amount, cat, desc, ttype, created_at = row

    log_transaction_delete(user_id, tid, float(amount), cat)
    delete_transaction_db(user_id, transaction_id)

    return (
        f"🗑️ Deleted *#{tid}* — {fmt_amount(amount)} on {cat} "
        f"({desc or '—'}) from {fmt_datetime(created_at)}."
    )


@tool
def edit_transaction(
    user_id: int,
    transaction_id: int,
    amount: float = None,
    category: str = None,
    description: str = None,
    type: str = None,
):
    """
    Updates one or more fields of an existing transaction.
    Only fields you pass will change; omit fields to keep them as-is.
    - transaction_id: Numeric ID from search_transactions.
    - amount:      New amount (optional, must be > 0).
    - category:    New category (optional).
    - description: New description note (optional).
    - type:        'expense' or 'income' (optional).
    Always call search_transactions first to confirm the correct ID.
    """
    try:
        transaction_id = validate_transaction_id(transaction_id)
        if amount      is not None: amount      = validate_amount(amount)
        if category    is not None: category    = validate_category(category)
        if description is not None: description = validate_description(description)
        if type        is not None: type        = validate_type(type)
    except ValidationError as exc:
        return f"❌ Invalid input: {exc}"

    row = get_transaction_by_id(user_id, transaction_id)
    if not row:
        return f"❌ Transaction #{transaction_id} not found or does not belong to you."

    old_tid, old_amount, old_cat, old_desc, old_type, _ = row

    new_amount = amount      if amount      is not None else old_amount
    new_cat    = category    if category    is not None else old_cat
    new_desc   = description if description is not None else old_desc
    new_type   = type        if type        is not None else old_type

    update_transaction_db(
        user_id=user_id, transaction_id=transaction_id,
        amount=new_amount, category=new_cat,
        description=new_desc, ttype=new_type,
    )

    changes = {}
    if amount      is not None: changes["amount"]      = {"from": old_amount, "to": new_amount}
    if category    is not None: changes["category"]    = {"from": old_cat,    "to": new_cat}
    if description is not None: changes["description"] = {"from": old_desc,   "to": new_desc}
    if type        is not None: changes["type"]        = {"from": old_type,   "to": new_type}

    if not changes:
        return "No changes were made — you didn't specify any new values."

    log_transaction_edit(user_id, transaction_id, changes)

    lines = [f"✅ Updated *#{transaction_id}*:"]
    if "amount"      in changes: lines.append(f"• Amount: {fmt_amount(old_amount)} → {fmt_amount(new_amount)}")
    if "category"    in changes: lines.append(f"• Category: {old_cat} → {new_cat}")
    if "description" in changes: lines.append(f"• Description: {old_desc or '—'} → {new_desc or '—'}")
    if "type"        in changes: lines.append(f"• Type: {old_type} → {new_type}")
    return "\n".join(lines)
