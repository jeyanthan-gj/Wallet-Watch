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
