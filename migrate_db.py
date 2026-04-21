import sqlite3

def run_migration():
    print("Running database migration for EMI support...")
    DB_FILE = "expenses.db"
    if not os.path.exists(DB_FILE):
        print("Database file not found. Nothing to migrate.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE recurring_bills ADD COLUMN total_installments INTEGER;")
        print("Added column: total_installments")
    except sqlite3.OperationalError:
        print("Column total_installments already exists.")
        
    try:
        cursor.execute("ALTER TABLE recurring_bills ADD COLUMN remaining_installments INTEGER;")
        print("Added column: remaining_installments")
    except sqlite3.OperationalError:
        print("Column remaining_installments already exists.")
        
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    import os
    run_migration()
