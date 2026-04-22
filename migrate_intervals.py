import sqlite3
import os

def run_migration():
    print("Running database migration for Custom Intervals...")
    DB_FILE = "expenses.db"
    if not os.path.exists(DB_FILE):
        print("Database file not found.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE recurring_bills ADD COLUMN interval_months INTEGER DEFAULT 1;")
        print("Added column: interval_months")
    except sqlite3.OperationalError:
        print("Column interval_months already exists.")
        
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    run_migration()
