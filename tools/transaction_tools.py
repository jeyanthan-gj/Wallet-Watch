"""
tools/transaction_tools.py

Security hardening applied:
  [CRIT-4]  All tool args validated before hitting DB.
  [MED-9]   delete_transaction writes an audit log entry before deleting.
"""

from langchain_core.tools import tool
from database.manager import (
    get_transaction_by_id,
    search_transactions_db,
    delete_transaction_db,
    update_transaction_db,
)
from security.validators import (
    validate_amount,
    validate_type,
    validate_category,
    validate_description,
    validate_keyword,
    validate_limit,
    validate_transaction_id,
    ValidationError,
)
from security.audit_log import log_transaction_delete, log_transaction_edit


@tool
def search_transactions(user_id: int, keyword: str = None, category: str = None, limit: int = 10):
    """
    Searches recent transactions so the user can identify which one to edit or delete.
    Returns a numbered list with transaction IDs.
    - keyword: Optional text to match in description (e.g. 'lunch', 'netflix').
    - category: Optional category filter (e.g. 'Food', 'Entertainment').
    - limit: Max results to return (default 10, max 50).
    Always call this before delete_transaction or edit_transaction.
    """
    try:
        keyword  = validate_keyword(keyword)
        category = validate_category(category) if category else None
        limit    = validate_limit(limit)
    except ValidationError as exc:
        return f"Invalid input: {exc}"

    rows = search_transactions_db(user_id, keyword=keyword, category=category, limit=limit)
    if not rows:
        return "No matching transactions found. Try a different keyword or category."

    lines = ["Matching Transactions:\n"]
    for tid, amount, cat, desc, ttype, created_at in rows:
        date_str = created_at[:10]
        sign     = "-" if ttype == "expense" else "+"
        lines.append(f"#{tid} | {sign}Rs{amount} | {cat} | {desc or '-'} | {date_str}")
    lines.append("\nReply with the # number to delete or edit.")
    return "\n".join(lines)


@tool
def delete_transaction(user_id: int, transaction_id: int):
    """
    Permanently deletes a single transaction by its ID.
    IMPORTANT: Always call search_transactions first, show results, and get
    explicit user confirmation before calling this tool.
    - user_id: The user's ID (ownership verified server-side).
    - transaction_id: The numeric ID shown in search_transactions results.
    """
    try:
        transaction_id = validate_transaction_id(transaction_id)
    except ValidationError as exc:
        return f"Invalid input: {exc}"

    row = get_transaction_by_id(user_id, transaction_id)
    if not row:
        return f"Transaction #{transaction_id} not found or does not belong to you."

    tid, amount, cat, desc, ttype, created_at = row

    # Audit BEFORE deletion so the record always exists
    log_transaction_delete(user_id, tid, amount, cat)

    delete_transaction_db(user_id, transaction_id)
    return (
        f"Deleted: #{tid} - Rs{amount} on {cat} ({desc or '-'}) "
        f"from {created_at[:10]}."
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
    Only fields you pass will change; omit fields you want to keep.
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
        return f"Invalid input: {exc}"

    row = get_transaction_by_id(user_id, transaction_id)
    if not row:
        return f"Transaction #{transaction_id} not found or does not belong to you."

    old_tid, old_amount, old_cat, old_desc, old_type, _ = row

    new_amount = amount      if amount      is not None else old_amount
    new_cat    = category    if category    is not None else old_cat
    new_desc   = description if description is not None else old_desc
    new_type   = type        if type        is not None else old_type

    update_transaction_db(
        user_id=user_id,
        transaction_id=transaction_id,
        amount=new_amount,
        category=new_cat,
        description=new_desc,
        ttype=new_type,
    )

    changes = {}
    if amount      is not None: changes["amount"]      = {"from": old_amount, "to": new_amount}
    if category    is not None: changes["category"]    = {"from": old_cat,    "to": new_cat}
    if description is not None: changes["description"] = {"from": old_desc,   "to": new_desc}
    if type        is not None: changes["type"]        = {"from": old_type,   "to": new_type}

    if not changes:
        return "No changes were made - you did not specify any new values."

    log_transaction_edit(user_id, transaction_id, changes)

    lines = [f"Updated #{transaction_id}:"]
    if "amount"      in changes: lines.append(f"Amount: Rs{old_amount} to Rs{new_amount}")
    if "category"    in changes: lines.append(f"Category: {old_cat} to {new_cat}")
    if "description" in changes: lines.append(f"Description: {old_desc} to {new_desc}")
    if "type"        in changes: lines.append(f"Type: {old_type} to {new_type}")
    return "\n".join(lines)
