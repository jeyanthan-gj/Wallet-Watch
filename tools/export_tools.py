import os
import pandas as pd
from datetime import datetime
from langchain_core.tools import tool
from database.manager import get_filtered_expenses

EXPORT_DIR = "exports"

@tool
def export_expenses(user_id: int, format: str = "csv", category: str = None, start_date: str = None, end_date: str = None, type: str = None):
    """
    Exports expenses to a file (CSV or Excel) based on user filters.
    - user_id: The ID of the user.
    - format: Either 'csv' or 'excel'.
    - category: (Optional) Filter by category (e.g., Food, Travel).
    - start_date: (Optional) Start date (YYYY-MM-DD).
    - end_date: (Optional) End date (YYYY-MM-DD).
    - type: (Optional) 'expense' or 'income'.
    """
    os.makedirs(EXPORT_DIR, exist_ok=True)
    
    # Fetch data
    rows = get_filtered_expenses(user_id, category, start_date, end_date, type)
    
    if not rows:
        return "No data found for the specified filters."
    
    # Create DataFrame
    df = pd.DataFrame(rows, columns=["Amount", "Category", "Description", "Type", "Date"])
    
    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = "csv" if format.lower() == "csv" else "xlsx"
    filename = f"expenses_{user_id}_{timestamp}.{ext}"
    filepath = os.path.join(EXPORT_DIR, filename)
    
    # Save file
    if format.lower() == "csv":
        df.to_csv(filepath, index=False)
    else:
        df.to_excel(filepath, index=False, engine='openpyxl')
        
    return f"Export successful! Here is your {format} file.\nEXPORT_PATH:\"{filepath}\""
