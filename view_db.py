import sqlite3

def view_expenses():
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    
    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='expenses';")
    if not cursor.fetchone():
        print("❌ The database is empty or the table hasn't been created yet.")
        return

    cursor.execute("SELECT * FROM expenses ORDER BY created_at DESC")
    rows = cursor.fetchall()
    
    if not rows:
        print("📭 No expenses found in the database yet.")
    else:
        print(f"{'ID':<4} | {'User ID':<12} | {'Amount':<10} | {'Category':<12} | {'Description':<20} | {'Type':<8} | {'Date'}")
        print("-" * 90)
        for row in rows:
            # Handle potential None values for description
            desc = row[4] if row[4] else "N/A"
            print(f"{row[0]:<4} | {row[1]:<12} | {row[2]:<10.2f} | {row[3]:<12} | {desc:<20} | {row[5]:<8} | {row[6]}")

    conn.close()

if __name__ == "__main__":
    view_expenses()
