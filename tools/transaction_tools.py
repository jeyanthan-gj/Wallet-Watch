from langchain_core.tools import tool
from database.manager import (
    get_transaction_by_id,
    search_transactions_db,
    delete_transaction_db,
    update_transaction_db,
)


@tool
def search_transactions(user_id: int, keyword: str = None, category: str = None, limit: int = 10):
    """
    Searches recent transactions so the user can identify which one to edit or delete.
    Returns a numbered list with transaction IDs.
    - keyword: Optional text to match in description (e.g. 'lunch', 'netflix').
    - category: Optional category filter (e.g. 'Food', 'Entertainment').
    - limit: Max results to return (default 10).
    Always call this first before delete_transaction or edit_transaction
    so you have the correct transaction ID.
    """
    rows = search_transactions_db(user_id, keyword=keyword, category=category, limit=limit)
    if not rows:
        return "No matching transactions found. Try a different keyword or category."

    lines = ["🔍 *Matching Transactions:*\n"]
    for row in rows:
        tid, amount, cat, desc, ttype, created_at = row
        date_str = created_at[:10]
        sign = "-" if ttype == "expense" else "+"
        lines.append(
            f"*#{tid}* | {sign}₹{amount} | {cat} | {desc or '—'} | {date_str}"
        )
    lines.append("\n_Reply with the # number to delete or edit._")
    return "\n".join(lines)


@tool
def delete_transaction(user_id: int, transaction_id: int):
    """
    Permanently deletes a single transaction by its ID.
    IMPORTANT: Always call search_transactions first to confirm the ID with the user.
    Ask for confirmation before deleting — e.g. 'Are you sure you want to delete #42?'
    Only call this tool after the user confirms.
    - user_id: The user's ID (for ownership check).
    - transaction_id: The numeric ID shown in search_transactions results.
    """
    row = get_transaction_by_id(user_id, transaction_id)
    if not row:
        return (
            f"❌ Transaction #{transaction_id} not found or doesn't belong to you."
        )

    tid, amount, cat, desc, ttype, created_at = row
    delete_transaction_db(user_id, transaction_id)
    return (
        f"🗑️ Deleted: #{tid} — ₹{amount} on {cat} ({desc or '—'}) "
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
    Only the fields you pass will be changed; omit fields you want to keep.
    - transaction_id: The numeric ID from search_transactions results.
    - amount: New amount (optional).
    - category: New category like Food, Transport, Salary (optional).
    - description: New description note (optional).
    - type: 'expense' or 'income' (optional).
    Always call search_transactions first to confirm the correct ID.
    """
    row = get_transaction_by_id(user_id, transaction_id)
    if not row:
        return (
            f"❌ Transaction #{transaction_id} not found or doesn't belong to you."
        )

    old_tid, old_amount, old_cat, old_desc, old_type, old_date = row

    new_amount = amount if amount is not None else old_amount
    new_cat = category if category is not None else old_cat
    new_desc = description if description is not None else old_desc
    new_type = type if type is not None else old_type

    update_transaction_db(
        user_id=user_id,
        transaction_id=transaction_id,
        amount=new_amount,
        category=new_cat,
        description=new_desc,
        ttype=new_type,
    )

    changes = []
    if amount is not None:
        changes.append(f"amount ₹{old_amount} → ₹{new_amount}")
    if category is not None:
        changes.append(f"category '{old_cat}' → '{new_cat}'")
    if description is not None:
        changes.append(f"description '{old_desc}' → '{new_desc}'")
    if type is not None:
        changes.append(f"type '{old_type}' → '{new_type}'")

    if not changes:
        return "No changes were made — you didn't specify any new values."

    return (
        f"✅ Updated #{transaction_id}:\n" + "\n".join(f"• {c}" for c in changes)
    )
