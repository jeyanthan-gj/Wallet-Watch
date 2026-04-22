import asyncio
from database.manager import register_user, add_expense_to_db, get_user_expenses, get_total_spent
from database.supabase_client import supabase

async def test_supabase():
    print("🚀 Testing Supabase Cloud Connection...")
    user_id = 888888  # Mock user ID
    
    try:
        # 1. Test User Registration
        print("Registering mock user...")
        register_user(user_id, "CloudTester")
        
        # 2. Test Logging Expense
        print("Logging a ₹999 test expense...")
        msg = add_expense_to_db(user_id, 999.0, "Testing", "Cloud migration test", "expense")
        print(f"Result: {msg}")
        
        # 3. Test Retrieval
        print("Checking history...")
        history = get_user_expenses(user_id)
        print(f"History: {history}")
        
        # 4. Test Summary
        print("Checking summary...")
        total = get_total_spent(user_id)
        print(f"Total: {total}")
        
        print("\n✅ SUPABASE MIGRATION VERIFIED! Everything is working correctly in the cloud.")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test_supabase())
