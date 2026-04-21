import sqlite3
import os

# Database file location (in the parent directory of this module)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, "expenses.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT, -- NULL or 'Total' for global limit
            amount REAL NOT NULL,
            period TEXT DEFAULT 'monthly',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, category)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recurring_bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            day_of_month INTEGER NOT NULL,
            type TEXT DEFAULT 'expense',
            last_processed_month TEXT, -- YYYY-MM
            is_active INTEGER DEFAULT 1,
            total_installments INTEGER,
            remaining_installments INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def add_expense_to_db(user_id: int, amount: float, category: str, description: str, exp_type: str):
    """Saves a transaction to the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO expenses (user_id, amount, category, description, type)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, amount, category, description, exp_type))
    conn.commit()
    conn.close()
    return f"Successfully saved {exp_type}: ${amount} for {description} ({category})"

def get_user_expenses(user_id: int, limit: int = 5):
    """Fetches the last N expenses for a specific user."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT amount, category, description, type, created_at 
        FROM expenses 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    ''', (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return "No expenses found."
    
    history = "\n".join([f"- ${r[0]} on {r[1]} ({r[2]}) at {r[4]}" for r in rows])
    return f"Last {len(rows)} transactions:\n{history}"

def get_total_spent(user_id: int):
    """Calculates total spend for a user."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT SUM(amount) FROM expenses WHERE user_id = ? AND type = "expense"', (user_id,))
    total = cursor.fetchone()[0]
    conn.close()
    return f"Total spending to date: ${total if total else 0.0}"

def get_expenses_in_range(user_id: int, start_date: str, end_date: str):
    """Fetches all expenses for a user between two dates (YYYY-MM-DD)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT amount, category, description, type, created_at 
        FROM expenses 
        WHERE user_id = ? 
        AND date(created_at) BETWEEN date(?) AND date(?)
        ORDER BY created_at ASC
    ''', (user_id, start_date, end_date))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_filtered_expenses(user_id: int, category: str = None, start_date: str = None, end_date: str = None, exp_type: str = None):
    """Fetches expenses with optional filters for category, date range, and type."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    query = "SELECT amount, category, description, type, created_at FROM expenses WHERE user_id = ?"
    params = [user_id]
    
    if category:
        query += " AND category = ?"
        params.append(category)
    if exp_type:
        query += " AND type = ?"
        params.append(exp_type)
    if start_date and end_date:
        query += " AND date(created_at) BETWEEN date(?) AND date(?)"
        params.extend([start_date, end_date])
    elif start_date:
        query += " AND date(created_at) >= date(?)"
        params.append(start_date)
    elif end_date:
        query += " AND date(created_at) <= date(?)"
        params.append(end_date)
        
    query += " ORDER BY created_at ASC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return rows

def upsert_budget(user_id: int, category: str, amount: float):
    """Sets or updates a budget for a category (or 'Total')."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO budgets (user_id, category, amount)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, category) DO UPDATE SET amount = excluded.amount
    ''', (user_id, category, amount))
    conn.commit()
    conn.close()

def get_budgets(user_id: int):
    """Retrieves all budgets for a user."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT category, amount FROM budgets WHERE user_id = ?', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return {row[0] if row[0] else 'Total': row[1] for row in rows}

def get_monthly_summary(user_id: int):
    """Calculates total income and total expense for the current month."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Current month spending
    cursor.execute('''
        SELECT type, SUM(amount) 
        FROM expenses 
        WHERE user_id = ? 
        AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now') 
        GROUP BY type
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    
    summary = {"income": 0.0, "expense": 0.0}
    for row in rows:
        summary[row[0].lower()] = row[1]
    return summary

def get_category_monthly_spend(user_id: int, category: str):
    """Calculates total spend for a specific category in the current month."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT SUM(amount) 
        FROM expenses 
        WHERE user_id = ? 
        AND category = ? 
        AND type = 'expense'
        AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')
    ''', (user_id, category))
    total = cursor.fetchone()[0]
    conn.close()
    return total if total else 0.0

def add_recurring_bill(user_id: int, amount: float, category: str, description: str, day_of_month: int, btype: str = 'expense', installments: int = None):
    """Adds a new recurring transaction with optional installment limit."""
    from datetime import datetime
    now = datetime.now()
    current_day = now.day
    # If added AFTER the day of the month, mark as processed for this month to start next month
    last_processed = now.strftime("%Y-%m") if current_day >= day_of_month else None
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO recurring_bills (user_id, amount, category, description, day_of_month, type, last_processed_month, total_installments, remaining_installments)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, amount, category, description, day_of_month, btype, last_processed, installments, installments))
    conn.commit()
    conn.close()

def decrement_installments(bill_id: int):
    """Reduces the remaining installments count and deactivates if zero."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE recurring_bills SET remaining_installments = remaining_installments - 1 WHERE id = ?', (bill_id,))
    cursor.execute('UPDATE recurring_bills SET is_active = 0 WHERE id = ? AND remaining_installments <= 0', (bill_id,))
    conn.commit()
    conn.close()

def get_active_recurring_bills(user_id: int):
    """Fetches all active recurring bills for a user."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, amount, category, description, day_of_month, type, last_processed_month, remaining_installments 
        FROM recurring_bills 
        WHERE user_id = ? AND is_active = 1
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def mark_bill_processed(bill_id: int, month_str: str):
    """Updates the last processed month for a recurring bill."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE recurring_bills SET last_processed_month = ? WHERE id = ?', (month_str, bill_id))
    conn.commit()
    conn.close()

def delete_recurring_bill(bill_id: int):
    """Deactivates a recurring bill."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE recurring_bills SET is_active = 0 WHERE id = ?', (bill_id,))
    conn.commit()
    conn.close()
